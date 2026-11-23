from pathlib import Path

import yaml


def test_trust_secret_versions_are_scoped_to_the_service() -> None:
    stack = yaml.safe_load(Path("stacks/main/trust-agent.yml").read_text(encoding="utf-8"))
    secret_names = stack["services"]["trust-agent"]["secrets"]
    assert len(secret_names) == 4
    for reference in secret_names:
        definition = stack["secrets"][reference["source"]]
        assert definition["name"] == f'{reference["source"]}-${{TRUST_AGENT_CONFIG_VERSION:?err}}'
