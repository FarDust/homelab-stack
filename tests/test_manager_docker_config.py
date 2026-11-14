"""Regression for the manager Docker daemon's diagnostic logging policy."""

import json
from pathlib import Path


def test_manager_daemon_keeps_mtu_and_disables_debug() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "host-config/docker/manager-daemon.json").read_text(encoding="utf-8"))
    assert config["debug"] is False
    assert config["mtu"] == 1280
