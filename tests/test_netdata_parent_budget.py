"""Contract tests for the Netdata parent image and memory budget.

Decision record: docs/adr/netdata_parent_memory_budget_adr.md.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/main/bridges.yml"
ADR = ROOT / "docs/adr/netdata_parent_memory_budget_adr.md"
# First release with the parent metadata fixes (obsolete charts released, cleanup no longer stalls).
MIN_VERSION = (2, 12, 2)


def _parent() -> dict:
    return yaml.safe_load(STACK.read_text())["services"]["netdata-parent"]


def test_parent_image_is_pinned_to_a_fixed_release_and_digest() -> None:
    image = _parent()["image"]
    match = re.fullmatch(r"netdata/netdata:v(\d+)\.(\d+)\.(\d+)@sha256:[0-9a-f]{64}", image)
    assert match, f"netdata-parent image must be an exact vX.Y.Z tag plus digest, got {image!r}"
    assert tuple(int(part) for part in match.groups()) >= MIN_VERSION


def test_parent_memory_budget_states_limit_and_reservation() -> None:
    resources = _parent()["deploy"]["resources"]
    assert resources["limits"]["memory"] == "3G"
    assert resources["reservations"]["memory"] == "2G"


def test_budget_adr_records_swap_and_rollback() -> None:
    text = ADR.read_text()
    for needle in ("## Context", "## Decision", "## Alternatives", "## Consequences", "## Verification", "swap", "Rollback", "v2.12.1"):
        assert needle in text, f"ADR is missing {needle!r}"
