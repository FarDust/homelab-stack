"""Contract tests for the rclone-fixer cache scan budget.

Decision record: docs/adr/rclone_fixer_cache_scan_budget_adr.md.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/main/maintenance.yml"
ADR = ROOT / "docs/adr/rclone_fixer_cache_scan_budget_adr.md"


def _fixer() -> dict:
    return yaml.safe_load(STACK.read_text())["services"]["rclone-fixer"]


def _environment() -> dict[str, str]:
    pairs = (item.split("=", 1) for item in _fixer()["environment"])
    return {key: value for key, value in pairs}


def test_cache_scan_is_bounded_to_the_root_entry() -> None:
    env = _environment()
    assert env.get("RCLONE_CACHE_SCAN_MAX_ENTRIES") == "1", "the per-cycle cache walk must stay bounded"
    assert "RCLONE_CACHE_SCAN_SECONDS" not in env, "a longer scan deadline would read the disk longer"


def test_controller_skips_the_ephemeral_node() -> None:
    constraints = _fixer()["deploy"]["placement"]["constraints"]
    assert "node.labels.node.ephemeral != true" in constraints
    assert not any("node.hostname" in c or "node.id" in c for c in constraints), "no host pinning"


def test_memory_budget_is_unchanged() -> None:
    resources = _fixer()["deploy"]["resources"]
    assert resources["limits"]["memory"] == "64M"
    assert resources["reservations"]["memory"] == "8M"


def test_adr_records_decision_and_rollback() -> None:
    text = ADR.read_text()
    for heading in ("## Context", "## Decision", "## Alternatives", "## Consequences", "## Verification", "## Rollback"):
        assert heading in text, f"ADR is missing {heading!r}"
    assert "RCLONE_CACHE_SCAN_MAX_ENTRIES" in text.split("## Rollback", 1)[1]
