#!/usr/bin/env python3
"""
Probe every qwen3.5:* model via the LiteLLM proxy (high-end Ollama route) with
per-request debug logging on the proxy.

Uses OpenAI-compatible POST /v1/chat/completions with litellm_request_debug=true
so LiteLLM emits the raw provider request/response for that call in container logs.

Usage:
  source .env
  python3 stacks/llms/ollama_qwen35_chat_probe.py

Env:
  LITELLM_PROBE_BASE — default https://litellm.${LOCAL_DOMAIN}/v1 (no trailing slash)
  LITELLM_API_KEY — defaults to LITELLM_MASTER_KEY
  LITELLM_QWEN35_MODELS — optional comma-separated model ids (e.g. qwen3.5:9b,qwen3.5:35b).
    When set, skips discovery; use when LiteLLM only lists qwen3.5:* and Ollama /api/tags is unreachable.
  OLLAMA_TAGS_BASE — default https://ollama.${LOCAL_DOMAIN}; used only to discover
    concrete tags when /v1/models does not list individual qwen3.5:* names
  LITELLM_REQUEST_DEBUG — default 1 (set 0 to disable litellm_request_debug in body)
  LITELLM_PROBE_DEBUG — default 0; set 1 to print discovery steps and URLs on stderr
  VERIFY_TLS — default 0
  HTTP_TIMEOUT_S — default 600
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_PROMPT = os.environ.get("OLLAMA_PROBE_PROMPT", "Reply with exactly: OK")


def _require_local_domain() -> str:
    domain = os.environ.get("LOCAL_DOMAIN", "").strip()
    if not domain:
        raise SystemExit("LOCAL_DOMAIN must be set to the cluster base domain (for example: LOCAL_DOMAIN=example.internal)")
    return domain


def _litellm_v1_base() -> str:
    b = os.environ.get("LITELLM_PROBE_BASE", "").strip().rstrip("/")
    if b:
        return b
    domain = _require_local_domain()
    return f"https://litellm.{domain}/v1"


def _ollama_tags_base() -> str:
    b = os.environ.get("OLLAMA_TAGS_BASE", "").strip().rstrip("/")
    if b:
        return b
    domain = _require_local_domain()
    return f"https://ollama.{domain}"


def _api_key() -> str:
    return (os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_MASTER_KEY") or "").strip()


def _ctx() -> ssl.SSLContext:
    if os.environ.get("VERIFY_TLS", "0").lower() in {"1", "true", "yes"}:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _timeout() -> float:
    return float(os.environ.get("HTTP_TIMEOUT_S", "600"))


def _truthy(name: str, default: str) -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes"}


def _probe_debug(msg: str) -> None:
    if _truthy("LITELLM_PROBE_DEBUG", "0"):
        print(f"[litellm-probe] {msg}", file=sys.stderr)


def _request(
    url: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
) -> tuple[int, Any]:
    h = dict(headers or {})
    if data is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, context=_ctx(), timeout=_timeout()) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(raw) if raw.strip() else {}


def _concrete_qwen35_from_litellm_models(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for m in payload.get("data", []) or []:
        mid = str(m.get("id") or m.get("model") or "")
        if mid.startswith("qwen3.5:") and "*" not in mid:
            out.append(mid)
    return sorted(set(out))


def _qwen35_tags_from_ollama(base: str) -> List[str]:
    url = f"{base}/api/tags"
    _probe_debug(f"GET {url}")
    status, data = _request(url, method="GET")
    if status != 200:
        raise RuntimeError(f"unexpected status {status} from {url}")
    names = [
        str(x["name"])
        for x in data.get("models", [])
        if str(x.get("name", "")).startswith("qwen3.5:")
    ]
    return sorted(set(names))


def _litellm_ids(data: Dict[str, Any]) -> List[str]:
    return [str(m.get("id") or "") for m in data.get("data", []) or []]


def discover_qwen35_models(
    litellm_v1: str, auth_headers: Dict[str, str], ollama_tags_base: str
) -> List[str]:
    override = os.environ.get("LITELLM_QWEN35_MODELS", "").strip()
    if override:
        models = sorted({x.strip() for x in override.split(",") if x.strip()})
        _probe_debug(f"using LITELLM_QWEN35_MODELS ({len(models)} ids)")
        return models

    url = f"{litellm_v1}/models"
    _probe_debug(f"GET {url}")
    status, data = _request(url, method="GET", headers=auth_headers)
    if status != 200:
        raise RuntimeError(f"/v1/models returned HTTP {status}")
    concrete = _concrete_qwen35_from_litellm_models(data)
    if concrete:
        _probe_debug(f"concrete qwen3.5:* from LiteLLM: {len(concrete)}")
        return concrete

    ids = _litellm_ids(data)
    has_wildcard = "qwen3.5:*" in ids
    _probe_debug(
        "LiteLLM has no per-tag qwen3.5:* entries; "
        f"wildcard qwen3.5:* in list={has_wildcard}. Trying Ollama tags…"
    )
    try:
        return _qwen35_tags_from_ollama(ollama_tags_base)
    except urllib.error.HTTPError as e:
        hint = _http_error_hint(
            e.code,
            where="Ollama GET /api/tags",
            url=f"{ollama_tags_base}/api/tags",
        )
        raise RuntimeError(
            f"{hint} "
            "LiteLLM only exposes qwen3.5:* (wildcard), so we need either a working "
            "Ollama /api/tags (same host as OLLAMA_API_BASE / governance) or set "
            "LITELLM_QWEN35_MODELS=qwen3.5:9b,qwen3.5:35b,... explicitly."
        ) from e


def _http_error_hint(code: int, *, where: str, url: str) -> str:
    domain = _require_local_domain()
    if code == 502:
        return (
            f"HTTP {code} on {where} ({url}): Traefik could not reach a healthy upstream "
            "(LiteLLM/Ollama task restarting, no healthy replica, or connect timeout). "
            "Retry; check `docker service ps` and Traefik/backend logs."
        )
    if code == 503:
        return (
            f"HTTP {code} on {where} ({url}): upstream unavailable or no server in pool. "
            "Check service health and deploy state."
        )
    if code == 404:
        return (
            f"HTTP {code} on {where} ({url}): Traefik default 404 or no router for this host/path. "
            f"Confirm the llms stack is deployed and Host(`ollama.{domain}`) routes to Ollama; "
            f"`curl -k https://ollama.{domain}/api/tags` should return JSON with models, not Traefik 404."
        )
    return f"HTTP {code} on {where} ({url})."


def chat_completions_payload(model: str, litellm_request_debug: bool) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": DEFAULT_PROMPT}],
        "max_tokens": int(os.environ.get("LITELLM_PROBE_MAX_TOKENS", "32")),
        "temperature": 0.0,
        "stream": False,
        "litellm_request_debug": litellm_request_debug,
    }


def main() -> int:
    key = _api_key()
    if not key:
        print(
            "Set LITELLM_API_KEY or LITELLM_MASTER_KEY (after source .env).",
            file=sys.stderr,
        )
        return 1

    litellm_v1 = _litellm_v1_base()
    ollama_tags = _ollama_tags_base()
    auth_headers = {"Authorization": f"Bearer {key}"}

    try:
        models = discover_qwen35_models(litellm_v1, auth_headers, ollama_tags)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        hint = _http_error_hint(
            e.code,
            where="LiteLLM GET /v1/models",
            url=f"{litellm_v1}/models",
        )
        print(f"{hint}\nBody: {err_body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Failed to discover qwen3.5 models: {e}", file=sys.stderr)
        return 1

    if not models:
        print("No qwen3.5:* models found (LiteLLM /v1/models and Ollama /api/tags).")
        return 0

    dbg = _truthy("LITELLM_REQUEST_DEBUG", "1")
    print(f"LiteLLM base: {litellm_v1}")
    print(f"Tag source fallback (if needed): {ollama_tags}/api/tags")
    print(f"Models: {len(models)}  litellm_request_debug={dbg}\n")

    for model in models:
        payload = chat_completions_payload(model, dbg)
        print("---")
        print(f"model: {model}")
        print("payload:")
        print(json.dumps(payload, indent=2))
        try:
            body_bytes = json.dumps(payload).encode("utf-8")
            status, body = _request(
                f"{litellm_v1}/chat/completions",
                method="POST",
                data=body_bytes,
                headers=auth_headers,
            )
            print(f"HTTP {status}")
            choice0 = (body.get("choices") or [{}])[0]
            msg = (choice0.get("message") or {}).get("content", "")
            err = body.get("error")
            print("error:", err)
            if msg:
                print("content:", repr(msg[:500]))
            usage = body.get("usage")
            if usage:
                print("usage:", usage)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:800]
            print(f"HTTP {e.code}: {err_body}")
        except Exception as e:
            print(f"error: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
