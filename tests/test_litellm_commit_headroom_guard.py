"""Contract tests for the LiteLLM commit-headroom guard.

Decision record: docs/adr/litellm_commit_headroom_guard_adr.md.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
GUARD = ROOT / "stacks/llms/configs/litellm/commit_headroom_guard.py"
CONFIG = ROOT / "stacks/llms/configs/litellm/config.yaml"
STACK = ROOT / "stacks/llms/governance.yml"
GIB = 1024**3
NOW = 1_800_000_000.0
OLLAMA = "https://ollama.local.example"
QWEN = [{"litellm_params": {"model": "ollama_chat/qwen3.5:9b", "api_base": OLLAMA}}]
WILDCARD = [{"litellm_params": {"model": "ollama_chat/qwen3.5:*", "api_base": OLLAMA}}]
LOW_END = [
    {
        "litellm_params": {
            "model": "ollama_chat/qwen3.5:2b",
            "api_base": "https://ollama-low-end.local.example",
        }
    }
]
CLOUD = [{"litellm_params": {"model": "vertex_ai/gemini-2.5-flash"}}]
ROUTES = {
    "n8n-chat": QWEN,
    "qwen3.5:9b": WILDCARD,
    "n8n-chat-low-end": LOW_END,
    "gemini-2.5-flash": CLOUD,
}


class _HTTPException(Exception):
    def __init__(
        self, status_code: int, detail: str, headers: dict | None = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch):
    custom_logger = types.ModuleType("litellm.integrations.custom_logger")
    custom_logger.CustomLogger = object
    fastapi = types.ModuleType("fastapi")
    fastapi.HTTPException = _HTTPException
    for name, mod in (
        ("litellm", types.ModuleType("litellm")),
        ("litellm.integrations", types.ModuleType("litellm.integrations")),
        ("litellm.integrations.custom_logger", custom_logger),
        ("fastapi", fastapi),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("commit_headroom_guard", GUARD)
    loaded = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules, "commit_headroom_guard", loaded
    )  # dataclasses resolve their module
    spec.loader.exec_module(loaded)
    return loaded


def _vector(value) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [NOW, value]}],
        },
    }


class FakeSignals:
    def __init__(
        self,
        headroom=str(10 * GIB),
        sampled_at=str(NOW - 30),
        resident=(),
        fail: str | None = None,
    ):
        self.headroom = headroom
        self.sampled_at = sampled_at
        self.resident = list(resident)
        self.fail = fail
        self.calls: list[str] = []

    async def __call__(self, url: str, params):
        self.calls.append(url)
        if url.endswith("/api/ps"):
            if self.fail == "ollama":
                raise ConnectionError("ollama down")
            return {"models": [{"name": n} for n in self.resident]}
        if self.fail == "prometheus":
            raise ConnectionError("prometheus down")
        query = params["query"]
        if query.startswith("memory_guard_commit_headroom_bytes"):
            return (
                self.headroom
                if isinstance(self.headroom, dict)
                else _vector(self.headroom)
            )
        return (
            self.sampled_at
            if isinstance(self.sampled_at, dict)
            else _vector(self.sampled_at)
        )


def _env(**overrides) -> dict:
    env = {"OLLAMA_API_BASE": OLLAMA, "COMMIT_GUARD_KEY_ALIASES": "*"}
    env.update(overrides)
    return env


def _key(alias="n8n"):
    return types.SimpleNamespace(key_alias=alias)


def _guard(module, signals, env=None, routes=ROUTES):
    def deployments(model):
        if routes is None:
            raise RuntimeError("router not ready")
        return routes.get(model, [])

    return module.CommitHeadroomGuard(
        env=_env() if env is None else env,
        fetch_json=signals,
        deployments=deployments,
        clock=lambda: NOW,
    )


def _call(guard, model="n8n-chat", alias="n8n"):
    data = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    return asyncio.run(guard.async_pre_call_hook(_key(alias), None, data, "completion"))


def test_below_floor_refuses_with_503_retry_after_and_reason(module):
    guard = _guard(module, FakeSignals(headroom=str(int(1.1 * GIB))))
    with pytest.raises(_HTTPException) as caught:
        _call(guard)
    assert caught.value.status_code == 503
    assert caught.value.headers == {"Retry-After": "120"}
    assert "COMMIT_HEADROOM_LOW" in caught.value.detail
    assert "qwen3.5:9b" in caught.value.detail and "1.1 GiB" in caught.value.detail
    assert (
        "6.0 GiB floor" in caught.value.detail
        and "COMMIT_GUARD_KEY_ALIASES" in caught.value.detail
    )


def test_above_floor_passes(module):
    data = _call(_guard(module, FakeSignals(headroom=str(12 * GIB))))
    assert data["model"] == "n8n-chat"


def test_wildcard_route_is_guarded_by_requested_tag(module):
    with pytest.raises(_HTTPException):
        _call(_guard(module, FakeSignals(headroom=str(GIB))), model="qwen3.5:9b")


def test_resident_model_passes_even_below_floor(module):
    signals = FakeSignals(headroom=str(GIB), resident=["qwen3.5:9b"])
    assert _call(_guard(module, signals))["model"] == "n8n-chat"
    assert not any("/api/v1/query" in url for url in signals.calls)


def test_ollama_ps_failure_treats_model_as_cold(module):
    with pytest.raises(_HTTPException):
        _call(_guard(module, FakeSignals(headroom=str(GIB), fail="ollama")))


def test_custom_floor_is_honoured(module):
    env = _env(COMMIT_GUARD_FLOOR_GIB="12")
    with pytest.raises(_HTTPException):
        _call(_guard(module, FakeSignals(headroom=str(10 * GIB)), env=env))


@pytest.mark.parametrize(
    ("signals", "reason"),
    [
        (
            FakeSignals(
                headroom={
                    "status": "success",
                    "data": {"resultType": "vector", "result": []},
                }
            ),
            "absent",
        ),
        (FakeSignals(sampled_at=str(NOW - 600)), "600 s old"),
        (FakeSignals(fail="prometheus"), "Prometheus query failed"),
        (FakeSignals(headroom="NaN"), "finite"),
        (FakeSignals(headroom="-5"), "finite"),
        (FakeSignals(headroom="abc"), "not a number"),
        (FakeSignals(headroom={"status": "error"}), "did not succeed"),
    ],
)
def test_missing_stale_or_malformed_signal_fails_closed(module, signals, reason):
    with pytest.raises(_HTTPException) as caught:
        _call(_guard(module, signals))
    assert caught.value.status_code == 503
    assert "COMMIT_HEADROOM_UNKNOWN" in caught.value.detail
    assert reason in caught.value.detail


def test_missing_signal_fails_open_only_when_documented_setting_says_so(module):
    env = _env(COMMIT_GUARD_ON_UNKNOWN="open")
    assert (
        _call(_guard(module, FakeSignals(fail="prometheus"), env=env))["model"]
        == "n8n-chat"
    )


def test_dark_by_default(module):
    signals = FakeSignals(headroom=str(GIB))
    env = {"OLLAMA_API_BASE": OLLAMA}
    assert _call(_guard(module, signals, env=env))["model"] == "n8n-chat"
    assert signals.calls == []


def test_per_key_flag_only_guards_listed_aliases(module):
    env = _env(COMMIT_GUARD_KEY_ALIASES="commit-guard-qa")
    assert (
        _call(_guard(module, FakeSignals(headroom=str(GIB)), env=env), alias="n8n")[
            "model"
        ]
        == "n8n-chat"
    )
    with pytest.raises(_HTTPException):
        _call(
            _guard(module, FakeSignals(headroom=str(GIB)), env=env),
            alias="commit-guard-qa",
        )


@pytest.mark.parametrize(
    "model", ["gemini-2.5-flash", "n8n-chat-low-end", "unknown-model"]
)
def test_unrelated_models_pass_without_signal_reads(module, model):
    signals = FakeSignals(headroom=str(GIB), fail="prometheus")
    assert _call(_guard(module, signals), model=model)["model"] == model
    assert signals.calls == []


def test_router_errors_never_block_requests(module):
    signals = FakeSignals(headroom=str(GIB))
    assert _call(_guard(module, signals, routes=None))["model"] == "n8n-chat"


def test_misconfigured_guard_refuses_only_flagged_ollama_requests(module):
    env = _env(COMMIT_GUARD_FLOOR_GIB="six")
    guard = _guard(module, FakeSignals(), env=env)
    with pytest.raises(_HTTPException) as caught:
        _call(guard)
    assert (
        "COMMIT_GUARD_MISCONFIGURED" in caught.value.detail
        and "COMMIT_GUARD_FLOOR_GIB" in caught.value.detail
    )
    assert _call(guard, model="gemini-2.5-flash")["model"] == "gemini-2.5-flash"
    dark = _guard(
        module,
        FakeSignals(),
        env={"OLLAMA_API_BASE": OLLAMA, "COMMIT_GUARD_FLOOR_GIB": "six"},
    )
    assert _call(dark)["model"] == "n8n-chat"


def test_guard_is_wired_into_the_gateway_and_dark_by_default():
    config = yaml.safe_load(CONFIG.read_text())
    assert (
        "commit_headroom_guard.proxy_handler_instance"
        in config["litellm_settings"]["callbacks"]
    )
    stack = yaml.safe_load(STACK.read_text())
    litellm = stack["services"]["litellm"]
    targets = {c["target"] for c in litellm["configs"]}
    assert "/app/config/commit_headroom_guard.py" in targets
    env = litellm["environment"]
    assert "COMMIT_GUARD_KEY_ALIASES=${LITELLM_COMMIT_GUARD_KEY_ALIASES:-}" in env
    assert "COMMIT_GUARD_FLOOR_GIB=${LITELLM_COMMIT_GUARD_FLOOR_GIB:-6}" in env
    assert "COMMIT_GUARD_ON_UNKNOWN=closed" in env
