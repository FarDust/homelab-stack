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
    assert names == ["minecraft-chat", "chatgpt-subscription-sol", "gemini-2.5-flash"]
    for name in names:
        deployments = _deployments(config, name)
        assert deployments, name
        for deployment in deployments:
            params = deployment["litellm_params"]
            assert not params["model"].startswith("ollama"), name
            assert "api_base" not in params, name


def test_minecraft_chat_local_aliases_are_removed() -> None:
    config = _load()
    text = CONFIG.read_text()
    assert "minecraft-chat-local" not in text
    assert "minecraft-chat-low-end" not in text
    assert {m["model_name"] for m in config["model_list"]}.isdisjoint(
        {"minecraft-chat-local", "minecraft-chat-low-end"}
    )
