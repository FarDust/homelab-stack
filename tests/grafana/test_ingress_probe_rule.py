"""Grafana rule ingress_probe_down must fire when a probe fails.

The old A = probe_success == 0 with C = gt 0 never fired: a failing probe yields 0 and 0 > 0 is
false.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RULES = Path(__file__).resolve().parents[2] / "stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml"


def rule(uid: str) -> dict:
    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    for group in data["groups"]:
        for item in group["rules"]:
            if item["uid"] == uid:
                return item
    raise AssertionError(f"rule {uid} not found in {RULES}")


def query(item: dict, ref: str) -> dict:
    return next(d for d in item["data"] if d["refId"] == ref)


def fires(item: dict, probe_success: float) -> bool:
    evaluator = query(item, "C")["model"]["conditions"][0]["evaluator"]
    threshold = evaluator["params"][0]
    return {"gt": probe_success > threshold, "lt": probe_success < threshold}[evaluator["type"]]


def test_query_returns_raw_probe_success():
    expr = query(rule("ingress_probe_down"), "A")["model"]["expr"]
    assert expr == 'probe_success{job="blackbox",monitor_group="ingress_control_plane"}'


def test_failing_probe_fires_and_healthy_probe_does_not():
    item = rule("ingress_probe_down")
    assert fires(item, 0.0)
    assert not fires(item, 1.0)


def test_condition_and_states_unchanged():
    item = rule("ingress_probe_down")
    assert item["condition"] == "C"
    assert (item["noDataState"], item["execErrState"], item["for"]) == ("OK", "OK", "2m")
