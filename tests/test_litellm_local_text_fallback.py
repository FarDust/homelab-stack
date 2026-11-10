"""Contract tests for the local text-only LiteLLM fallback.

Decision record: docs/adr/litellm_local_text_fallback_adr.md.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "stacks/llms/configs/litellm/config.yaml"
GUARD = ROOT / "stacks/llms/configs/litellm/text_only_fallback_guard.py"
STACK = ROOT / "stacks/llms/governance.yml"
LOCAL = "local-fallback"
TOOL_ALIASES = ("zeus-brain", "trust-agent-chat", "minecraft-chat")


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def _chain(config: dict, group: str) -> list[str]:
    chain: list[str] = []
    pending = [group]
    while pending:
        current = pending.pop()
        for rule in config["router_settings"]["fallbacks"]:
            for target in rule.get(current, []):
                if target not in chain:
                    chain.append(target)
                    pending.append(target)
    return chain


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


def _guard(monkeypatch: pytest.MonkeyPatch):
    """Load the hook with minimal stand-ins for the gateway's runtime-only imports."""
    custom_logger = types.ModuleType("litellm.integrations.custom_logger")
    custom_logger.CustomLogger = object
    fastapi = types.ModuleType("fastapi")
    fastapi.HTTPException = _HTTPException
    for name, module in (
        ("litellm", types.ModuleType("litellm")),
        ("litellm.integrations", types.ModuleType("litellm.integrations")),
        ("litellm.integrations.custom_logger", custom_logger),
        ("fastapi", fastapi),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("text_only_fallback_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_fallback_deployment_exists_and_is_node_internal() -> None:
    entries = [m for m in _config()["model_list"] if m["model_name"] == LOCAL]
    assert len(entries) == 1
    params = entries[0]["litellm_params"]
    assert params["model"] == "ollama_chat/gemma3:4b"
    assert params["api_base"] == "os.environ/OLLAMA_TEXT_FALLBACK_API_BASE"
    assert params["timeout"] <= 120


def test_only_text_only_aliases_reach_the_local_model() -> None:
    config = _config()
    reaching = {
        name
        for rule in config["router_settings"]["fallbacks"]
        for name in rule
        if LOCAL in _chain(config, name)
    }
    assert reaching == {"zeus-cheap", "zeus-text"}
    for alias in TOOL_ALIASES:
        assert LOCAL not in _chain(config, alias), alias


def test_local_model_is_the_last_hop_of_each_text_only_chain() -> None:
    config = _config()
    for alias in ("zeus-cheap", "zeus-text"):
        assert _chain(config, alias)[-1] == LOCAL


def test_guard_aliases_match_the_fallback_map(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config()
    guard = _guard(monkeypatch)
    reaching = {
        name for rule in config["router_settings"]["fallbacks"] for name in rule if LOCAL in _chain(config, name)
    }
    assert set(guard.TEXT_ONLY_ALIASES) == reaching
    assert "text_only_fallback_guard.proxy_handler_instance" in config["litellm_settings"]["callbacks"]


def test_guard_disables_fallbacks_for_tool_requests_on_text_only_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _guard(monkeypatch)
    handler = guard.proxy_handler_instance
    data = {"model": "zeus-text", "tools": [{"type": "function", "function": {"name": "x"}}]}
    out = asyncio.run(handler.async_pre_call_hook(None, None, data, "completion"))
    assert out["disable_fallbacks"] is True


def test_guard_leaves_plain_text_requests_with_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _guard(monkeypatch)
    handler = guard.proxy_handler_instance
    data = {"model": "zeus-text", "messages": [{"role": "user", "content": "hola"}]}
    out = asyncio.run(handler.async_pre_call_hook(None, None, data, "completion"))
    assert "disable_fallbacks" not in out


def test_guard_rejects_tool_requests_sent_straight_to_the_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = _guard(monkeypatch)
    handler = guard.proxy_handler_instance
    with pytest.raises(Exception) as err:
        asyncio.run(handler.async_pre_call_hook(None, None, {"model": LOCAL, "functions": [{"name": "x"}]}, "completion"))
    assert getattr(err.value, "status_code", None) == 400


def test_local_service_uses_a_node_local_volume_and_stable_placement() -> None:
    stack = yaml.safe_load(STACK.read_text())
    service = stack["services"]["ollama-text-fallback"]
    assert stack["volumes"]["ollama_text_fallback_data"] == {"driver": "local"}
    assert service["volumes"] == ["ollama_text_fallback_data:/root/.ollama"]
    constraints = service["deploy"]["placement"]["constraints"]
    assert "node.labels.node.ephemeral != true" in constraints
    assert not any("hostname" in c for c in constraints)
    assert "@sha256:" in service["image"]
    assert "ports" not in service
    assert not any(label.startswith("traefik.enable") for label in service["deploy"].get("labels", []))
    litellm_env = stack["services"]["litellm"]["environment"]
    assert "OLLAMA_TEXT_FALLBACK_API_BASE=http://llms-governance_ollama-text-fallback:11434" in litellm_env
    assert "gemma3:4b" in " ".join(service["command"])
