"""Refuse a cold Ollama model load on gabriel-pc while the Windows host is short of commit headroom.

Every cold load of a model on the high-end Ollama (the WSL guest of gabriel-pc) charges about 10 GB of host commit to
``vmmemWSL`` while the model is on the GPU. When the Windows free virtual memory (commit headroom) is already low, a
load can exhaust commit and crash the desktop. This pre-call hook answers HTTP 503 with ``Retry-After`` instead of
starting the load. The host signal is ``memory_guard_commit_headroom_bytes`` published by memory-guard through the
node-exporter textfile collector of gabriel-pc-wsl and read from Prometheus.

Dark by default: the guard acts only for API keys whose alias is listed in ``COMMIT_GUARD_KEY_ALIASES`` (``*`` means
every key). Decision record: docs/adr/litellm_commit_headroom_guard_adr.md; runbook:
docs/runbooks/litellm-commit-headroom-guard.md.
"""

import asyncio
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

LOG = logging.getLogger("commit_headroom_guard")

GIB = 1024**3
FLAG = "COMMIT_GUARD_KEY_ALIASES"
HEADROOM_METRIC = "memory_guard_commit_headroom_bytes"
TIMESTAMP_METRIC = "memory_guard_commit_sample_timestamp_seconds"
ERROR_CODE_LOW = "COMMIT_HEADROOM_LOW"
ERROR_CODE_UNKNOWN = "COMMIT_HEADROOM_UNKNOWN"
ERROR_CODE_MISCONFIGURED = "COMMIT_GUARD_MISCONFIGURED"
CODE_PATH = "stacks/llms/configs/litellm/commit_headroom_guard.py"


class SignalUnavailable(Exception):
    """The host headroom signal is missing, stale or malformed."""


class GuardMisconfigured(Exception):
    """A COMMIT_GUARD_* setting cannot be parsed."""


@dataclass(frozen=True)
class Settings:
    key_aliases: frozenset[str]
    floor_bytes: float
    prometheus_url: str
    host_label: str
    max_age_s: float
    fail_open: bool
    retry_after_s: int
    guarded_api_bases: frozenset[str]
    ollama_url: str
    timeout_s: float

    def applies_to(self, key_alias: str | None) -> bool:
        return _flag_applies(self.key_aliases, key_alias)


def parse_key_aliases(env: Mapping[str, str]) -> frozenset[str]:
    """The per-key feature flag: empty (the default) keeps the guard dark, ``*`` enables it for every key."""
    return frozenset(
        alias.strip() for alias in env.get(FLAG, "").split(",") if alias.strip()
    )


def _flag_applies(key_aliases: frozenset[str], key_alias: str | None) -> bool:
    if not key_aliases:
        return False
    return "*" in key_aliases or (key_alias is not None and key_alias in key_aliases)


def _number(
    env: Mapping[str, str], name: str, default: str, *, minimum: float
) -> float:
    raw = env.get(name, default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise GuardMisconfigured(f"{name}={raw!r} is not a number") from exc
    if not math.isfinite(value) or value < minimum:
        raise GuardMisconfigured(f"{name}={raw!r} must be a finite number >= {minimum}")
    return value


def load_settings(env: Mapping[str, str]) -> Settings:
    """Parse the COMMIT_GUARD_* environment. Raises GuardMisconfigured with the offending setting."""
    on_unknown = env.get("COMMIT_GUARD_ON_UNKNOWN", "closed").strip().lower()
    if on_unknown not in ("closed", "open"):
        raise GuardMisconfigured(
            f"COMMIT_GUARD_ON_UNKNOWN={on_unknown!r} must be 'closed' or 'open'"
        )
    bases = {
        base.strip().rstrip("/")
        for base in env.get("COMMIT_GUARD_API_BASES", "").split(",")
        if base.strip()
    }
    ollama_base = env.get("OLLAMA_API_BASE", "").strip().rstrip("/")
    if ollama_base:
        bases.add(ollama_base)
    if not bases:
        raise GuardMisconfigured(
            "no guarded api_base: set OLLAMA_API_BASE or COMMIT_GUARD_API_BASES"
        )
    return Settings(
        key_aliases=parse_key_aliases(env),
        floor_bytes=_number(env, "COMMIT_GUARD_FLOOR_GIB", "11", minimum=0) * GIB,
        prometheus_url=env.get(
            "COMMIT_GUARD_PROMETHEUS_URL", "http://prometheus:9090"
        ).rstrip("/"),
        host_label=env.get("COMMIT_GUARD_HOST_LABEL", "gabriel-pc"),
        max_age_s=_number(env, "COMMIT_GUARD_MAX_AGE_S", "180", minimum=1),
        fail_open=on_unknown == "open",
        retry_after_s=int(_number(env, "COMMIT_GUARD_RETRY_AFTER_S", "120", minimum=1)),
        guarded_api_bases=frozenset(bases),
        ollama_url=env.get(
            "COMMIT_GUARD_OLLAMA_URL", "http://llms-governance_ollama:11434"
        ).rstrip("/"),
        timeout_s=_number(env, "COMMIT_GUARD_TIMEOUT_S", "2", minimum=0.1),
    )


@dataclass(frozen=True)
class Headroom:
    free_bytes: float
    age_s: float


def parse_headroom(
    headroom_body: object, timestamp_body: object, now: float
) -> Headroom:
    """Read one Prometheus instant-query vector for each metric. Raises SignalUnavailable with the reason."""

    def single_value(body: object, metric: str) -> float:
        if not isinstance(body, dict) or body.get("status") != "success":
            raise SignalUnavailable(f"Prometheus query for {metric} did not succeed")
        data = body.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "vector":
            raise SignalUnavailable(f"Prometheus answer for {metric} is not a vector")
        result = data.get("result")
        if not isinstance(result, list) or not result:
            raise SignalUnavailable(
                f"{metric} is absent (memory-guard publisher not running or WSL down)"
            )
        if len(result) != 1:
            raise SignalUnavailable(f"{metric} has {len(result)} series, expected 1")
        sample = result[0].get("value") if isinstance(result[0], dict) else None
        if not isinstance(sample, list) or len(sample) != 2:
            raise SignalUnavailable(f"{metric} sample is malformed")
        try:
            value = float(sample[1])
        except (TypeError, ValueError) as exc:
            raise SignalUnavailable(
                f"{metric} value {sample[1]!r} is not a number"
            ) from exc
        if not math.isfinite(value) or value < 0:
            raise SignalUnavailable(
                f"{metric} value {value!r} is not a finite non-negative number"
            )
        return value

    free_bytes = single_value(headroom_body, HEADROOM_METRIC)
    sampled_at = single_value(timestamp_body, TIMESTAMP_METRIC)
    age_s = now - sampled_at
    if age_s < -60:
        raise SignalUnavailable(f"{TIMESTAMP_METRIC} is {-age_s:.0f} s in the future")
    return Headroom(free_bytes=free_bytes, age_s=max(age_s, 0.0))


def ollama_model_name(deployment_model: str, requested: str) -> str:
    """``ollama_chat/qwen3.5:9b`` -> ``qwen3.5:9b``; a wildcard route serves the requested tag itself."""
    name = (
        deployment_model.split("/", 1)[1]
        if "/" in deployment_model
        else deployment_model
    )
    name = requested if "*" in name else name
    # Ollama reports untagged models with the implicit ``:latest`` tag in /api/ps.
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"


def resolve_api_base(raw: object) -> str:
    """LiteLLM resolves ``os.environ/NAME`` at load; resolve it here too so a literal never misses silently."""
    value = str(raw or "").strip()
    if value.startswith("os.environ/"):
        value = os.environ.get(value.removeprefix("os.environ/"), "")
    return value.rstrip("/")


def guarded_ollama_models(
    deployments: Sequence[Mapping[str, object]], requested: str, settings: Settings
) -> list[str]:
    """The Ollama models on a guarded api_base that this request can load."""
    models: list[str] = []
    for deployment in deployments:
        params = deployment.get("litellm_params")
        if not isinstance(params, Mapping):
            continue
        api_base = resolve_api_base(params.get("api_base"))
        model = str(params.get("model") or "")
        if api_base in settings.guarded_api_bases and model.startswith(
            ("ollama/", "ollama_chat/")
        ):
            models.append(ollama_model_name(model, requested))
    return models


Fetch = Callable[[str, Mapping[str, str]], Awaitable[object]]
Deployments = Callable[[str], Sequence[Mapping[str, object]]]


async def _httpx_get_json(
    url: str, params: Mapping[str, str], timeout_s: float
) -> object:
    import httpx

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.get(url, params=dict(params))
        response.raise_for_status()
        return response.json()


def _router_deployments(model: str) -> Sequence[Mapping[str, object]]:
    from litellm.proxy.proxy_server import llm_router

    if llm_router is None:
        raise RuntimeError("LiteLLM router is not initialised")
    return llm_router.get_model_list(model_name=model) or []


class CommitHeadroomGuard(CustomLogger):
    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        fetch_json: Fetch | None = None,
        deployments: Deployments | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__()
        source = os.environ if env is None else env
        self._key_aliases = parse_key_aliases(source)
        self._settings: Settings | None = None
        self._config_error: str | None = None
        try:
            self._settings = load_settings(source)
        except GuardMisconfigured as exc:
            self._config_error = str(exc)
            LOG.error("commit_headroom_guard misconfigured: %s", exc)
        timeout = self._settings.timeout_s if self._settings else 2.0
        self._fetch = fetch_json or (
            lambda url, params: _httpx_get_json(url, params, timeout)
        )
        self._deployments = deployments or _router_deployments
        self._clock = clock

    def _refuse(self, code: str, reason: str, retry_after_s: int) -> HTTPException:
        LOG.warning("commit_headroom_guard refused: %s: %s", code, reason)
        return HTTPException(
            status_code=503,
            detail=f"{code}: {reason}; retry after {retry_after_s} s (code path {CODE_PATH}, flag {FLAG})",
            headers={"Retry-After": str(retry_after_s)},
        )

    async def _resident(self, settings: Settings) -> set[str]:
        body = await self._fetch(f"{settings.ollama_url}/api/ps", {})
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise SignalUnavailable("Ollama /api/ps answer is malformed")
        return {
            str(m.get(field))
            for m in body["models"]
            if isinstance(m, dict)
            for field in ("name", "model")
            if m.get(field)
        }

    async def _headroom(self, settings: Settings) -> Headroom:
        selector = f'{{host="{settings.host_label}"}}'
        url = f"{settings.prometheus_url}/api/v1/query"
        # min/max collapse a transient duplicate series (node-exporter reschedule) into one conservative value.
        try:
            headroom_body, timestamp_body = await asyncio.gather(
                self._fetch(url, {"query": f"min({HEADROOM_METRIC}{selector})"}),
                self._fetch(url, {"query": f"max({TIMESTAMP_METRIC}{selector})"}),
            )
        except Exception as exc:
            raise SignalUnavailable(
                f"Prometheus query failed: {type(exc).__name__}: {exc}"
            ) from exc
        return parse_headroom(headroom_body, timestamp_body, self._clock())

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        model = data.get("model") if isinstance(data, dict) else None
        if not isinstance(model, str) or not model:
            return data
        key_alias = getattr(user_api_key_dict, "key_alias", None)
        settings = self._settings
        if settings is None:
            # Misconfigured: refuse only flagged callers' Ollama requests, never unrelated models.
            if not _flag_applies(self._key_aliases, key_alias):
                return data
            try:
                deployments = self._deployments(model)
            except Exception as exc:  # noqa: BLE001 - router errors must never block a request
                LOG.error(
                    "commit_headroom_guard could not resolve deployments for %s: %s",
                    model,
                    exc,
                )
                return data
            if any(
                isinstance(d.get("litellm_params"), Mapping)
                and str(d["litellm_params"].get("model") or "").startswith(
                    ("ollama/", "ollama_chat/")
                )
                for d in deployments
            ):
                raise self._refuse(
                    ERROR_CODE_MISCONFIGURED, self._config_error or "unknown", 300
                )
            return data
        if not settings.applies_to(key_alias):
            return data
        try:
            models = guarded_ollama_models(self._deployments(model), model, settings)
        except Exception as exc:  # noqa: BLE001 - router errors must never block a request
            # Classification failure: the request may be unrelated, so it passes; the failure is logged.
            LOG.error(
                "commit_headroom_guard could not resolve deployments for %s: %s",
                model,
                exc,
            )
            return data
        if not models:
            return data
        try:
            resident = await self._resident(settings)
        except Exception as exc:  # noqa: BLE001 - unknown residency is treated as a cold load
            LOG.warning(
                "commit_headroom_guard: Ollama /api/ps unavailable (%s); treating %s as cold",
                exc,
                models,
            )
            resident = set()
        if all(m in resident for m in models):
            return data  # already on the GPU: no new commit charge
        try:
            headroom = await self._headroom(settings)
        except SignalUnavailable as exc:
            if settings.fail_open:
                LOG.warning(
                    "commit_headroom_guard fail-open (COMMIT_GUARD_ON_UNKNOWN=open): %s",
                    exc,
                )
                return data
            raise self._refuse(
                ERROR_CODE_UNKNOWN,
                f"cold load of {', '.join(models)} refused: host commit headroom unknown ({exc})",
                settings.retry_after_s,
            ) from exc
        if headroom.age_s > settings.max_age_s:
            reason = f"host commit headroom sample is {headroom.age_s:.0f} s old (max {settings.max_age_s:.0f} s)"
            if settings.fail_open:
                LOG.warning("commit_headroom_guard fail-open: %s", reason)
                return data
            raise self._refuse(
                ERROR_CODE_UNKNOWN,
                f"cold load of {', '.join(models)} refused: {reason}",
                settings.retry_after_s,
            )
        if headroom.free_bytes < settings.floor_bytes:
            raise self._refuse(
                ERROR_CODE_LOW,
                f"cold load of {', '.join(models)} refused: {settings.host_label} free virtual memory "
                f"{headroom.free_bytes / GIB:.1f} GiB is below the {settings.floor_bytes / GIB:.1f} GiB floor "
                f"(sample age {headroom.age_s:.0f} s)",
                settings.retry_after_s,
            )
        return data


proxy_handler_instance = CommitHeadroomGuard()
