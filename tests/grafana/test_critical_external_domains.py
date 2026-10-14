"""Critical external domain watch: a NextDNS block (2026-10-14, storage.googleapis.com) must alert.

A blocked domain resolves to blockpage.nextdns.io, so the TLS handshake for the real hostname fails
and probe_success drops to 0.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "stacks/main/configs/grafana/provisioning/alerting/behavioral_rules.yml"
TARGETS = ROOT / "stacks/main/configs/prometheus/blackbox_targets.yaml"
BLACKBOX = ROOT / "stacks/main/configs/blackbox/blackbox.yml"
CRITICAL = {
    "storage.googleapis.com", "www.googleapis.com", "github.com", "raw.githubusercontent.com", "pypi.org",
    "files.pythonhosted.org", "registry.npmjs.org", "huggingface.co", "ghcr.io", "registry-1.docker.io",
    "api.anthropic.com", "login.tailscale.com", "api.gitguardian.com",
}


def rule(uid: str) -> dict:
    for group in yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]:
        for item in group["rules"]:
            if item["uid"] == uid:
                return item
    raise AssertionError(f"rule {uid} not found")


def test_every_critical_domain_has_a_tls_probe():
    entries = [e for e in yaml.safe_load(TARGETS.read_text(encoding="utf-8")) if e["labels"].get("monitor_group") == "critical_external_dns"]
    assert {e["labels"]["service"] for e in entries} == CRITICAL
    for entry in entries:
        assert entry["targets"] == [f"{entry['labels']['service']}:443"]
        assert entry["labels"]["module"] == "tls_connect"


def test_tls_connect_module_does_a_tls_handshake():
    module = yaml.safe_load(BLACKBOX.read_text(encoding="utf-8"))["modules"]["tls_connect"]
    assert module["prober"] == "tcp" and module["tcp"]["tls"] is True
    assert module["tcp"]["preferred_ip_protocol"] == "ip4"  # cluster nodes have no IPv6 route


def test_rule_fires_on_failure_only():
    item = rule("critical_external_domain_unreachable")
    query = next(d for d in item["data"] if d["refId"] == "A")["model"]["expr"]
    assert query == 'probe_success{job="blackbox",monitor_group="critical_external_dns"}'
    evaluator = next(d for d in item["data"] if d["refId"] == "C")["model"]["conditions"][0]["evaluator"]
    fires = lambda value: {"lt": value < evaluator["params"][0], "gt": value > evaluator["params"][0]}[evaluator["type"]]  # noqa: E731
    assert fires(0.0) and not fires(1.0)
    assert item["for"] == "10m"
