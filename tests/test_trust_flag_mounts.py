from pathlib import Path

import yaml


def test_trust_secret_versions_are_scoped_to_the_service() -> None:
    stack = yaml.safe_load(Path("stacks/main/trust-agent.yml").read_text(encoding="utf-8"))
    secret_names = stack["services"]["trust-agent"]["secrets"]
    assert len(secret_names) == 6
    for reference in secret_names:
        definition = stack["secrets"][reference["source"]]
        assert definition["name"] == f'{reference["source"]}-${{TRUST_AGENT_CONFIG_VERSION:?err}}'


def test_flag_secret_sources_require_nonempty_private_paths() -> None:
    stack = yaml.safe_load(Path("stacks/main/trust-agent.yml").read_text(encoding="utf-8"))
    assert stack["secrets"]["trust_agent_unleash_admin"]["file"] == "${TRUST_AGENT_UNLEASH_ADMIN_SECRET_FILE:?err}"
    assert stack["secrets"]["trust_agent_japan_service_credential"]["file"] == "${TRUST_AGENT_JAPAN_SERVICE_SECRET_FILE:?err}"
