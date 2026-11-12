"""Contract tests for the ClickHouse self-telemetry budget on HDD-backed nodes.

Decision record: docs/adr/hdd_node_io_budget_adr.md.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
STACK = ROOT / "stacks/main/storage.yml"
OVERRIDE = ROOT / "stacks/main/configs/clickhouse/system-logs.xml"
RULES = ROOT / "stacks/main/configs/prometheus/alert.rules"
ADR = ROOT / "docs/adr/hdd_node_io_budget_adr.md"
# The tables that produced the constant background writes.
REMOVED = {"trace_log", "text_log", "metric_log", "asynchronous_metric_log", "part_log"}
KEPT = {"query_log", "crash_log"}


def _stack() -> dict:
    return yaml.safe_load(STACK.read_text())


def test_image_is_an_exact_release_plus_digest() -> None:
    image = _stack()["services"]["clickhouse"]["image"]
    assert re.fullmatch(r"clickhouse/clickhouse-server:\d+\.\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", image), image


def test_override_is_mounted_into_config_d() -> None:
    stack = _stack()
    mounts = {c["source"]: c["target"] for c in stack["services"]["clickhouse"]["configs"]}
    assert mounts["clickhouse_system_logs"] == "/etc/clickhouse-server/config.d/system-logs.xml"
    definition = stack["configs"]["clickhouse_system_logs"]
    assert definition["file"] == "./configs/clickhouse/system-logs.xml"
    assert "${CONFIG_VERSION" in definition["name"], "config name must be versioned"


def test_override_removes_the_noisy_tables_and_keeps_the_useful_ones() -> None:
    root = ET.parse(OVERRIDE).getroot()
    assert root.tag == "clickhouse"
    removed = {child.tag for child in root if child.attrib.get("remove") == "1"}
    assert REMOVED <= removed, f"missing removals: {sorted(REMOVED - removed)}"
    assert not KEPT & {child.tag for child in root}, "query_log and crash_log must stay enabled"


def test_io_alerts_exist() -> None:
    groups = yaml.safe_load(RULES.read_text())["groups"]
    alerts = {rule["alert"]: rule for group in groups for rule in group["rules"] if "alert" in rule}
    assert "node_pressure_io_waiting_seconds_total" in alerts["HostIoPressureSustained"]["expr"]
    assert "node_disk_io_time_seconds_total" in alerts["HostDiskSaturated"]["expr"]
    for name in ("HostIoPressureSustained", "HostDiskSaturated"):
        assert alerts[name]["for"] == "30m"


def test_adr_records_decision_and_rollback() -> None:
    text = ADR.read_text()
    for heading in ("## Context", "## Decision", "## Alternatives", "## Consequences", "## Verification", "## Rollback"):
        assert heading in text, f"ADR is missing {heading!r}"
    assert "system-logs.xml" in text.split("## Rollback", 1)[1]
