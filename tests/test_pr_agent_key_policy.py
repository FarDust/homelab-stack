from ast import literal_eval
from pathlib import Path
import re


def test_pr_agent_key_cache_read_is_exact_and_other_services_remain_write_only() -> None:
    path = Path(__file__).parents[1] / "stacks/main/configs/openbao/policies/trust-agent-admin.hcl"
    rules = {m.group(1): tuple(literal_eval(m.group(2))) for m in re.finditer(r'path "([^\"]+)" \{\s+capabilities = (\[[^\]]+\])\s+\}', path.read_text())}
    assert rules["secret/data/services/pr-agent/litellm"] == ("create", "update", "read")
    assert rules["secret/data/services/*"] == ("create", "update")


def test_minecraft_chat_key_cache_read_is_exact_and_other_services_remain_write_only() -> None:
    path = Path(__file__).parents[1] / "stacks/main/configs/openbao/policies/trust-agent-admin.hcl"
    rules = {m.group(1): tuple(literal_eval(m.group(2))) for m in re.finditer(r'path "([^\"]+)" \{\s+capabilities = (\[[^\]]+\])\s+\}', path.read_text())}
    assert rules["secret/data/services/minecraft-chat/litellm"] == ("create", "update", "read")
    assert rules["secret/data/services/*"] == ("create", "update")


def test_zeus_key_cache_read_is_exact_and_other_services_remain_write_only() -> None:
    path = Path(__file__).parents[1] / "stacks/main/configs/openbao/policies/trust-agent-admin.hcl"
    rules = {m.group(1): tuple(literal_eval(m.group(2))) for m in re.finditer(r'path "([^\"]+)" \{\s+capabilities = (\[[^\]]+\])\s+\}', path.read_text())}
    for service in ("zeus-brain", "zeus-cheap"):
        assert rules[f"secret/data/services/{service}/litellm"] == ("create", "update", "read")
    assert rules["secret/data/services/*"] == ("create", "update")
