import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import optuna
import requests

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    func,
    text as sql_text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class RetryableOllamaError(RuntimeError):
    """Raised for transient Ollama/proxy failures that should be retried."""


DEFAULT_HTTP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, application/x-ndjson",
    "Connection": "keep-alive",
    "Keep-Alive": "timeout=120, max=1000",
    "Cache-Control": "no-cache",
}



@dataclass(frozen=True)
class Config:
    # Endpoint
    model: str
    local_domain: str
    chat_url: str

    # Ladder search space
    min_ctx: int
    max_ctx: int
    ctx_step: int

    # Generation options
    num_predict: int
    temperature: float
    top_p: float
    seed: Optional[int]

    # Request body
    prompt: str
    prompt_mode: str  # "short" | "near_ctx"
    prompt_ctx_fraction: float

    # Runtime
    trials: int
    timeout_s: int
    verify_tls: bool
    chat_retries: int
    chat_retry_sleep_s: float
    prewarm_on_start: bool
    prewarm_num_ctx: int
    prewarm_num_predict: int
    optuna_seed: int
    # Postgres (required; trial rows always persisted)
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str
    pg_schema: str
    experiment_run_id: str


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v is not None and v != "" else default


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v is not None and v != "" else default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}


def _require_local_domain() -> str:
    domain = os.environ.get("LOCAL_DOMAIN", "").strip()
    if not domain:
        raise SystemExit("LOCAL_DOMAIN must be set to the cluster base domain (for example: LOCAL_DOMAIN=example.internal)")
    return domain


def load_config() -> Config:
    local_domain = _require_local_domain()
    model = os.environ.get("OLLAMA_MODEL", "qwen3.5:0.8b")

    # CanIRun.ai lists Qwen 3.5 0.8B / 9B with 32K context; we default to probing up to 32K.
    # Note: if your low-end Ollama service is configured with a smaller max context via
    # OLLAMA_CONTEXT_LENGTH, larger num_ctx values may be rejected or internally clamped.
    min_ctx = _env_int("MIN_CTX", 1024)
    max_ctx = _env_int("MAX_CTX", 32768)
    ctx_step = _env_int("CTX_STEP", 1024)

    num_predict = _env_int("NUM_PREDICT", 16)
    temperature = _env_float("TEMPERATURE", 0.0)
    top_p = _env_float("TOP_P", 1.0)
    seed_env = os.environ.get("SEED", "")
    seed: Optional[int] = int(seed_env) if seed_env != "" else None

    prompt = os.environ.get("PROMPT", "Return exactly: OK")
    prompt_mode = os.environ.get("PROMPT_MODE", "short")
    prompt_ctx_fraction = _env_float("PROMPT_CTX_FRACTION", 0.05)

    trials = _env_int("OPTUNA_TRIALS", 20)
    timeout_s = _env_int("HTTP_TIMEOUT_S", 120)
    verify_tls = _env_bool("VERIFY_TLS", False)
    chat_retries = _env_int("OLLAMA_CHAT_RETRIES", 3)
    chat_retry_sleep_s = _env_float("OLLAMA_CHAT_RETRY_SLEEP_S", 2.0)
    prewarm_on_start = _env_bool("OLLAMA_PREWARM_ON_START", False)
    prewarm_num_ctx = _env_int("OLLAMA_PREWARM_NUM_CTX", min_ctx)
    prewarm_num_predict = _env_int("OLLAMA_PREWARM_NUM_PREDICT", min(4, num_predict))
    optuna_seed = _env_int("OPTUNA_SEED", 1337)

    chat_url = os.environ.get(
        "OLLAMA_CHAT_URL",
        f"https://ollama-low-end.{local_domain}/api/chat",
    )

    pg_host = (os.environ.get("RESULTS_PG_HOST") or "").strip()
    pg_port = _env_int("RESULTS_PG_PORT", 5432)
    pg_user = (os.environ.get("RESULTS_PG_USER") or "").strip()
    pg_password = os.environ.get("RESULTS_PG_PASSWORD")
    if pg_password is None or pg_password == "":
        pw_file = os.environ.get("RESULTS_PG_PASSWORD_FILE", "").strip()
        if pw_file:
            pg_password = Path(pw_file).read_text(encoding="utf-8").strip()
    pg_database = (os.environ.get("RESULTS_PG_DATABASE") or "").strip()
    pg_schema = os.environ.get("RESULTS_PG_SCHEMA", "infra_experiments")
    if not pg_schema.isidentifier():
        raise SystemExit("RESULTS_PG_SCHEMA must be a valid identifier (e.g., infra_experiments)")
    experiment_run_id = os.environ.get("EXPERIMENT_RUN_ID", time.strftime("%Y%m%d_%H%M%S"))

    if not pg_host or not pg_user or not pg_database:
        raise SystemExit(
            "Missing required RESULTS_PG_HOST, RESULTS_PG_USER, and/or RESULTS_PG_DATABASE "
            "(Postgres storage is always enabled)."
        )
    if pg_password is None or pg_password == "":
        raise SystemExit(
            "Set RESULTS_PG_PASSWORD or RESULTS_PG_PASSWORD_FILE (Postgres storage is always enabled)."
        )

    return Config(
        model=model,
        local_domain=local_domain,
        chat_url=chat_url,
        min_ctx=min_ctx,
        max_ctx=max_ctx,
        ctx_step=ctx_step,
        num_predict=num_predict,
        temperature=temperature,
        top_p=top_p,
        seed=seed,
        prompt=prompt,
        prompt_mode=prompt_mode,
        prompt_ctx_fraction=prompt_ctx_fraction,
        trials=trials,
        timeout_s=timeout_s,
        verify_tls=verify_tls,
        chat_retries=chat_retries,
        chat_retry_sleep_s=chat_retry_sleep_s,
        prewarm_on_start=prewarm_on_start,
        prewarm_num_ctx=prewarm_num_ctx,
        prewarm_num_predict=prewarm_num_predict,
        optuna_seed=optuna_seed,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        pg_password=pg_password,
        pg_database=pg_database,
        pg_schema=pg_schema,
        experiment_run_id=experiment_run_id,
    )


def _safe_int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) else None


def _safe_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _safe_bigint(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def ns_to_s(ns: Optional[float]) -> Optional[float]:
    if ns is None:
        return None
    return ns / 1e9


def extract_token_metrics(response: Dict[str, Any]) -> Dict[str, Any]:
    prompt_eval_count = _safe_int(response.get("prompt_eval_count"))
    eval_count = _safe_int(response.get("eval_count"))
    prompt_eval_duration_ns = _safe_bigint(response.get("prompt_eval_duration"))
    eval_duration_ns = _safe_bigint(response.get("eval_duration"))
    total_duration_ns = _safe_bigint(response.get("total_duration"))
    load_duration_ns = _safe_bigint(response.get("load_duration"))

    prompt_seconds = ns_to_s(prompt_eval_duration_ns)
    eval_seconds = ns_to_s(eval_duration_ns)

    prompt_tps = None
    gen_tps = None
    if prompt_eval_count is not None and prompt_seconds and prompt_seconds > 0:
        prompt_tps = float(prompt_eval_count) / prompt_seconds
    if eval_count is not None and eval_seconds and eval_seconds > 0:
        gen_tps = float(eval_count) / eval_seconds

    return {
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "prompt_eval_duration_ns": prompt_eval_duration_ns,
        "eval_duration_ns": eval_duration_ns,
        "total_duration_ns": total_duration_ns,
        "load_duration_ns": load_duration_ns,
        "prompt_tokens_per_s": prompt_tps,
        "gen_tokens_per_s": gen_tps,
    }


def build_prompt(cfg: Config, num_ctx: int) -> str:
    if cfg.prompt_mode == "short":
        return cfg.prompt

    # "near_ctx": create a prompt that's large enough to encourage kv-cache usage.
    # Exact token counts are model-dependent, so we approximate via word count.
    # This intentionally stays bounded to avoid massive payloads.
    frac = max(0.0, min(1.0, cfg.prompt_ctx_fraction))
    target_tokens = int(num_ctx * frac)
    # Roughly 1 token ~= 0.75 words for English-ish text (very approximate).
    target_words = max(1, int(target_tokens / 0.75))
    filler = ("x " * target_words).strip()
    return f"{cfg.prompt}\n\nFILLER:\n{filler}\n"


def call_ollama_chat(
    cfg: Config,
    num_ctx: int,
    http_session: requests.Session,
    num_predict_override: Optional[int] = None,
) -> Dict[str, Any]:
    num_predict = cfg.num_predict if num_predict_override is None else num_predict_override

    payload: Dict[str, Any] = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": build_prompt(cfg, num_ctx)}],
        "stream": False,
        "options": {
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "num_predict": num_predict,
            # This is the key parameter we ladder over.
            "num_ctx": num_ctx,
        },
    }
    if cfg.seed is not None:
        payload["options"]["seed"] = cfg.seed

    retryable_exceptions = (RetryableOllamaError, requests.exceptions.RequestException)

    @retry(
        stop=stop_after_attempt(cfg.chat_retries),
        wait=wait_exponential(
            multiplier=cfg.chat_retry_sleep_s,
            min=cfg.chat_retry_sleep_s,
            max=max(cfg.chat_retry_sleep_s * 8, cfg.chat_retry_sleep_s),
        ),
        retry=retry_if_exception_type(retryable_exceptions),
        reraise=True,
    )
    def _do_request() -> Dict[str, Any]:
        resp = http_session.post(
            cfg.chat_url,
            json=payload,
            timeout=cfg.timeout_s,
            verify=cfg.verify_tls,
            headers=DEFAULT_HTTP_HEADERS,
        )

        if resp.status_code == 200:
            try:
                return resp.json()
            except json.JSONDecodeError as e:
                # Often happens when a proxy times out and returns HTML.
                raise RetryableOllamaError(f"Non-JSON response: {resp.text[:200]}") from e

        if resp.status_code in {502, 503, 504, 429}:
            raise RetryableOllamaError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        # Non-retryable HTTP status codes.
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    return _do_request()


def is_success(response: Dict[str, Any]) -> bool:
    # Success heuristic:
    # - no explicit error payload
    # - Ollama marks request done=true
    # Token counters are informative metrics only and may be absent.
    if isinstance(response.get("error"), (str, dict)):
        return False
    return response.get("done") is True


def main() -> int:
    cfg = load_config()
    http_session = requests.Session()

    # Ensure search space is monotonic and sensible.
    if cfg.min_ctx < 1:
        cfg.min_ctx = 1
    if cfg.max_ctx < cfg.min_ctx:
        raise SystemExit("MAX_CTX must be >= MIN_CTX")
    if cfg.ctx_step < 1:
        raise SystemExit("CTX_STEP must be >= 1")

    # Keep trials deterministic-ish.
    sampler = optuna.samplers.TPESampler(seed=cfg.optuna_seed, multivariate=True)
    pruner = optuna.pruners.MedianPruner(n_startup_trials=min(5, cfg.trials))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)

    SessionLocal = None
    ContextLadderTrial = None

    def record_trial_to_postgres(
        trial_number: int,
        num_ctx: int,
        ok: bool,
        elapsed_ms: int,
        err: Optional[str],
        metrics: Dict[str, Any],
    ) -> None:
        if SessionLocal is None or ContextLadderTrial is None:
            raise RuntimeError("Postgres ORM not initialized")

        session = None
        try:
            with SessionLocal() as session:
                row = ContextLadderTrial(
                    run_id=cfg.experiment_run_id,
                    trial_number=trial_number,
                    model=cfg.model,
                    num_ctx=num_ctx,
                    num_predict=cfg.num_predict,
                    temperature=cfg.temperature,
                    top_p=cfg.top_p,
                    prompt_mode=cfg.prompt_mode,
                    prompt_ctx_fraction=cfg.prompt_ctx_fraction,
                    success=ok,
                    elapsed_ms=elapsed_ms,
                    error=err,
                    prompt_eval_count=metrics.get("prompt_eval_count"),
                    eval_count=metrics.get("eval_count"),
                    prompt_eval_duration_ns=metrics.get("prompt_eval_duration_ns"),
                    eval_duration_ns=metrics.get("eval_duration_ns"),
                    total_duration_ns=metrics.get("total_duration_ns"),
                    load_duration_ns=metrics.get("load_duration_ns"),
                    prompt_tokens_per_s=metrics.get("prompt_tokens_per_s"),
                    gen_tokens_per_s=metrics.get("gen_tokens_per_s"),
                )
                session.add(row)
                session.commit()
        except Exception:
            # Suppress DB errors (infra experiments should still proceed).
            try:
                if session is not None:
                    session.rollback()
            except Exception:
                pass
            return

    db_url = (
        f"postgresql+psycopg2://{cfg.pg_user}:{cfg.pg_password}"
        f"@{cfg.pg_host}:{cfg.pg_port}/{cfg.pg_database}"
    )
    engine = create_engine(db_url, pool_pre_ping=True)

    # SQLAlchemy doesn't create schemas automatically; ensure it exists first.
    with engine.begin() as conn:
        conn.execute(sql_text(f"CREATE SCHEMA IF NOT EXISTS {cfg.pg_schema}"))

    Base = declarative_base()

    class _ContextLadderTrial(Base):  # type: ignore[misc]
        __tablename__ = "context_ladder_trials"
        __table_args__ = {"schema": cfg.pg_schema}

        id = Column(BigInteger, primary_key=True, autoincrement=True)
        run_id = Column(String, nullable=False)
        created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

        trial_number = Column(Integer, nullable=False)
        model = Column(Text, nullable=False)
        num_ctx = Column(Integer, nullable=False)
        num_predict = Column(Integer, nullable=False)
        temperature = Column(Float, nullable=False)
        top_p = Column(Float, nullable=False)
        prompt_mode = Column(Text, nullable=False)
        prompt_ctx_fraction = Column(Float, nullable=False)
        success = Column(Boolean, nullable=False)
        elapsed_ms = Column(Integer, nullable=False)
        error = Column(Text, nullable=True)

        prompt_eval_count = Column(Integer, nullable=True)
        eval_count = Column(Integer, nullable=True)
        prompt_eval_duration_ns = Column(BigInteger, nullable=True)
        eval_duration_ns = Column(BigInteger, nullable=True)
        total_duration_ns = Column(BigInteger, nullable=True)
        load_duration_ns = Column(BigInteger, nullable=True)
        prompt_tokens_per_s = Column(Float, nullable=True)
        gen_tokens_per_s = Column(Float, nullable=True)

    Base.metadata.create_all(bind=engine)

    # Best-effort indexes for querying by run/trial/context.
    with engine.begin() as conn:
        conn.execute(
            sql_text(
                f"CREATE INDEX IF NOT EXISTS context_ladder_trials_run_id_idx "
                f"ON {cfg.pg_schema}.context_ladder_trials (run_id)"
            )
        )
        conn.execute(
            sql_text(
                f"CREATE INDEX IF NOT EXISTS context_ladder_trials_trial_ctx_idx "
                f"ON {cfg.pg_schema}.context_ladder_trials (run_id, trial_number, num_ctx)"
            )
        )

    ContextLadderTrial = _ContextLadderTrial
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    if cfg.prewarm_on_start:
        try:
            print(
                f"Prewarming model={cfg.model} num_ctx={cfg.prewarm_num_ctx} "
                f"num_predict={cfg.prewarm_num_predict}..."
            )
            _ = call_ollama_chat(
                cfg,
                num_ctx=cfg.prewarm_num_ctx,
                http_session=http_session,
                num_predict_override=cfg.prewarm_num_predict,
            )
            print("Prewarm OK")
        except Exception as e:
            print(f"Prewarm failed (continuing): {e}")

    def objective(trial: optuna.Trial) -> float:
        num_ctx = trial.suggest_int("num_ctx", cfg.min_ctx, cfg.max_ctx, step=cfg.ctx_step)

        t0 = time.time()
        ok = False
        err: Optional[str] = None
        metrics: Dict[str, Any] = {}

        try:
            resp = call_ollama_chat(cfg, num_ctx=num_ctx, http_session=http_session)
            ok = is_success(resp)
            metrics = extract_token_metrics(resp)
        except Exception as e:  # noqa: BLE001 - we want to treat any failure as "break"
            err = str(e)
            ok = False

        elapsed_ms = int((time.time() - t0) * 1000)

        record_trial_to_postgres(trial.number, num_ctx, ok, elapsed_ms, err, metrics)

        # If it "breaks", return 0 so we can maximize the largest working context length.
        return float(num_ctx if ok else 0)

    study.optimize(objective, n_trials=cfg.trials)

    # Compute a clean "best working" context.
    successful = [t.params["num_ctx"] for t in study.trials if t.value and t.value > 0 and "num_ctx" in t.params]
    best_ctx = max(successful) if successful else None

    print("\nOptuna context ladder summary")
    print(f"Model: {cfg.model}")
    print(f"Chat URL: {cfg.chat_url}")
    print(f"Trials: {cfg.trials}")
    print(
        f"Results in Postgres: schema={cfg.pg_schema} "
        f"table=context_ladder_trials run_id={cfg.experiment_run_id}"
    )
    if best_ctx is None:
        print("No successful trials found (all attempts 'broke').")
        return 2

    print(f"Best working num_ctx: {best_ctx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
