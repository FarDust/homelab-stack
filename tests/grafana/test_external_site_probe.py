"""External site watch: autotransport.com timed out on 2026-10-09 without an alert.

See reports/2026-10-15-autotransport-probe.md.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml"
TARGETS = ROOT / "stacks/main/configs/prometheus/blackbox_targets.yaml"


def rule(uid: str) -> dict:
    for group in yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]:
        for item in group["rules"]:
            if item["uid"] == uid:
                return item
    raise AssertionError(f"rule {uid} not found")


def evaluator(item: dict) -> dict:
    return next(d for d in item["data"] if d["refId"] == "C")["model"]["conditions"][0]["evaluator"]


def query(item: dict) -> str:
    return next(d for d in item["data"] if d["refId"] == "A")["model"]["expr"]


def fires(item: dict, value: float) -> bool:
    ev = evaluator(item)
    return {"lt": value < ev["params"][0], "gt": value > ev["params"][0]}[ev["type"]]


def test_autotransport_has_an_http_probe():
    entries = [e for e in yaml.safe_load(TARGETS.read_text(encoding="utf-8")) if e["labels"].get("monitor_group") == "external_sites"]
    assert [e["targets"] for e in entries] == [["https://autotransport.com/"]]
    assert entries[0]["labels"]["module"] == "http_2xx"


def test_failed_rule_fires_on_failure_only():
    item = rule("external_site_probe_failed")
    assert query(item) == 'probe_success{job="blackbox",monitor_group="external_sites"}'
    assert fires(item, 0.0) and not fires(item, 1.0)
    assert item["for"] == "5m"


def test_missing_rule_fires_when_the_series_is_absent():
    item = rule("external_site_probe_missing")
    assert query(item) == 'absent(probe_success{job="blackbox",monitor_group="external_sites"})'
    assert fires(item, 1.0) and not fires(item, 0.0)  # absent() returns 1 only when no series exists
    assert item["for"] == "15m"
