from pathlib import Path

import yaml

CONFIG = Path(__file__).parents[1] / "stacks/llms/configs/litellm/config.yaml"


def _load() -> dict:
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


def _deployments(config: dict, name: str) -> list[dict]:
    return [m for m in config["model_list"] if m["model_name"] == name]


def test_minecraft_chat_uses_only_subscription_and_api_routes() -> None:
    config = _load()
    names = ["minecraft-chat", *_chain(config, "minecraft-chat")]
    assert names == ["minecraft-chat", "chatgpt-subscription-sol", "gemini-2.5-flash", "gpt-5-mini"]
    for name in names:
        deployments = _deployments(config, name)
        assert deployments, name
        for deployment in deployments:
            params = deployment["litellm_params"]
            assert params["model"].startswith(("chatgpt/", "vertex_ai/", "openai/")), name
            assert "api_base" not in params, name


def test_minecraft_chat_local_aliases_are_removed() -> None:
    config = _load()
    text = CONFIG.read_text()
    assert "minecraft-chat-local" not in text
    assert "minecraft-chat-low-end" not in text
    assert {m["model_name"] for m in config["model_list"]}.isdisjoint(
        {"minecraft-chat-local", "minecraft-chat-low-end"}
    )


def test_zeus_cheap_uses_only_subscription_and_api_routes() -> None:
    config = _load()
    names = ["zeus-cheap", *_chain(config, "zeus-cheap")]
    # The chain ends on the node-local text-only model (docs/adr/litellm_local_text_fallback_adr.md);
    # every hop before it is a subscription or API route.
    assert names == ["zeus-cheap", "gemini-3-flash-preview", "gpt-5-mini", "local-fallback"]
    assert _deployments(config, "zeus-cheap")[0]["litellm_params"]["model"] == "chatgpt/gpt-6-luna"
    for name in names[:-1]:
        deployments = _deployments(config, name)
        assert deployments, name
        for deployment in deployments:
            params = deployment["litellm_params"]
            assert params["model"].startswith(("chatgpt/", "vertex_ai/", "openai/")), name
            assert "api_base" not in params, name
    retry = config["router_settings"]["model_group_retry_policy"]["zeus-cheap"]
    assert retry == {"DefaultRetries": 0, "TimeoutErrorRetries": 0}


def test_zeus_brain_chain_ends_on_the_openai_api_and_has_no_local_route() -> None:
    config = _load()
    names = ["zeus-brain", *_chain(config, "zeus-brain")]
    assert names == ["zeus-brain", "chatgpt-subscription-sol", "gemini-3-flash-preview", "gpt-5"]
    assert _deployments(config, "zeus-brain")[0]["litellm_params"]["model"] == "chatgpt/gpt-6.1-terra"
    for name in names:
        deployments = _deployments(config, name)
        assert deployments, name
        for deployment in deployments:
            params = deployment["litellm_params"]
            assert params["model"].startswith(("chatgpt/", "vertex_ai/", "openai/")), name
            assert "api_base" not in params, name
    openai_routes = {
        name for name in ("minecraft-chat", "zeus-cheap", "zeus-brain")
        for chain_name in [name, *_chain(config, name)]
        for d in _deployments(config, chain_name)
        if d["litellm_params"]["model"].startswith("openai/")
    }
    assert openai_routes == {"minecraft-chat", "zeus-cheap", "zeus-brain"}  # every Zeus route ends on the API
    retry = config["router_settings"]["model_group_retry_policy"]["zeus-brain"]
    assert retry == {"DefaultRetries": 0, "TimeoutErrorRetries": 0}
