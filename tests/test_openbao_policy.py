from __future__ import annotations

import re
from ast import literal_eval
from pathlib import Path

POLICY_PATH = Path(__file__).parents[1] / "stacks/main/configs/openbao/policies/trust-agent-admin.hcl"


def _policy_capabilities() -> dict[str, tuple[str, ...]]:
    text = POLICY_PATH.read_text()
    return {
        match.group(1): tuple(literal_eval(match.group(2)))
        for match in re.finditer(
            r'path "([^"]+)" \{\s+capabilities = (\[[^\]]+\])\s+\}',
            text,
        )
    }


def test_graphify_key_cache_read_is_exact_and_broad_service_path_stays_write_only() -> None:
    capabilities = _policy_capabilities()

    assert capabilities["secret/data/services/graphify-headless/litellm"] == (
        "create",
        "update",
        "read",
    )
    assert capabilities["secret/data/services/*"] == ("create", "update")
