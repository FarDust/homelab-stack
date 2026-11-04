import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

DEFAULT_HTTP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, application/x-ndjson",
    "Connection": "keep-alive",
    "Keep-Alive": "timeout=120, max=1000",
    "Cache-Control": "no-cache",
}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def _safe_int(v: Any) -> Optional[int]:
    return v if isinstance(v, int) else None


def _safe_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _metrics(resp: Dict[str, Any]) -> Dict[str, Optional[float]]:
    prompt_eval_count = _safe_int(resp.get("prompt_eval_count"))
    eval_count = _safe_int(resp.get("eval_count"))
    prompt_eval_duration_ns = _safe_float(resp.get("prompt_eval_duration"))
    eval_duration_ns = _safe_float(resp.get("eval_duration"))

    prompt_tps = None
    gen_tps = None
    if prompt_eval_count and prompt_eval_duration_ns and prompt_eval_duration_ns > 0:
        prompt_tps = float(prompt_eval_count) / (prompt_eval_duration_ns / 1e9)
    if eval_count and eval_duration_ns and eval_duration_ns > 0:
        gen_tps = float(eval_count) / (eval_duration_ns / 1e9)

    return {
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "prompt_eval_duration_ns": prompt_eval_duration_ns,
        "eval_duration_ns": eval_duration_ns,
        "prompt_tokens_per_s": prompt_tps,
        "gen_tokens_per_s": gen_tps,
    }


def _base_url(chat_url: str) -> str:
    # Expected chat URL format: <scheme>://<host>/api/chat
    parsed = urlparse(chat_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _model_in_tags(tags_resp: Dict[str, Any], model: str) -> bool:
    models = tags_resp.get("models")
    if not isinstance(models, list):
        return False
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name == model:
            return True
    return False


def main() -> int:
    chat_url = os.environ.get("OLLAMA_LOWEND_CHAT_URL", "").strip()
    if not chat_url:
        domain = os.environ.get("LOCAL_DOMAIN", "").strip()
        if not domain:
            raise SystemExit("Set OLLAMA_LOWEND_CHAT_URL or LOCAL_DOMAIN (the cluster base domain)")
        chat_url = f"https://ollama-low-end.{domain}/api/chat"
    model = os.environ.get("OLLAMA_MODEL", "qwen3.5:2b-q4_K_M")
    verify_tls = _env_bool("VERIFY_TLS", False)
    timeout_s = _env_int("HTTP_TIMEOUT_S", 180)
    probe_num_ctx = _env_int("PROBE_NUM_CTX", 1024)
    probe_num_predict = _env_int("PROBE_NUM_PREDICT", 8)
    pre_pull_model = _env_bool("PRE_PULL_MODEL", True)
    pre_pull_timeout_s = _env_int("PRE_PULL_TIMEOUT_S", 900)
    poll_every_s = _env_float("PRE_PULL_POLL_EVERY_S", 5.0)
    probe_stream = _env_bool("PROBE_STREAM", False)
    http_session = requests.Session()

    base_url = _base_url(chat_url)
    pull_url = f"{base_url}/api/pull"
    tags_url = f"{base_url}/api/tags"

    print(f"probe_chat_url={chat_url}")
    print(f"probe_model={model}")

    if pre_pull_model:
        print("step=pre_pull start")
        try:
            pull_resp = http_session.post(
                # Keep a persistent TCP session to reduce reconnect churn under proxy load.
                pull_url,
                json={"name": model},
                timeout=timeout_s,
                verify=verify_tls,
                headers=DEFAULT_HTTP_HEADERS,
            )
            print(f"pre_pull_http_status={pull_resp.status_code}")
            if pull_resp.status_code != 200:
                print(f"pre_pull_error_body={pull_resp.text[:400]}")
        except Exception as exc:  # noqa: BLE001
            print(f"pre_pull_exception={exc}")

        print("step=wait_for_tags start")
        deadline = time.time() + pre_pull_timeout_s
        seen = False
        last_status = None
        last_error = None
        while time.time() < deadline:
            try:
                tags_resp = http_session.get(
                    tags_url,
                    timeout=timeout_s,
                    verify=verify_tls,
                    headers=DEFAULT_HTTP_HEADERS,
                )
                last_status = tags_resp.status_code
                if tags_resp.status_code == 200:
                    payload = tags_resp.json()
                    if _model_in_tags(payload, model):
                        seen = True
                        break
                else:
                    last_error = tags_resp.text[:200]
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(poll_every_s)

        print(f"wait_for_tags_seen={seen}")
        if not seen:
            print(f"wait_for_tags_last_status={last_status}")
            if last_error:
                print(f"wait_for_tags_last_error={last_error}")

    print("step=chat_probe start")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return exactly: OK"}],
        "stream": probe_stream,
        "options": {
            "temperature": 0.0,
            "top_p": 1.0,
            "num_predict": probe_num_predict,
            "num_ctx": probe_num_ctx,
        },
    }

    try:
        resp = http_session.post(
            chat_url,
            json=payload,
            timeout=timeout_s,
            verify=verify_tls,
            headers=DEFAULT_HTTP_HEADERS,
        )
        print(f"chat_http_status={resp.status_code}")
        if resp.status_code != 200:
            print(f"chat_error_body={resp.text[:500]}")
            return 2

        data = resp.json()
        done = data.get("done")
        err = data.get("error")
        print(f"chat_done={done}")
        print(f"chat_error={err}")
        print(f"chat_response_head={json.dumps(data)[:500]}")

        m = _metrics(data)
        print(f"prompt_eval_count={m['prompt_eval_count']}")
        print(f"eval_count={m['eval_count']}")
        print(f"prompt_tokens_per_s={m['prompt_tokens_per_s']}")
        print(f"gen_tokens_per_s={m['gen_tokens_per_s']}")

        return 0 if done is True and not err else 3
    except Exception as exc:  # noqa: BLE001
        print(f"chat_exception={exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
