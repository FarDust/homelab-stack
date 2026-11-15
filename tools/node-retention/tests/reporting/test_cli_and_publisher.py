"""Public CLI denial/help and the real publisher boundary, without host writes."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from node_retention.reporting import cli
from node_retention.reporting.adapters import publisher as publisher_module
from node_retention.reporting.adapters.publisher import CanonicalPublisher
from node_retention.reporting.config import ReportSettings
from node_retention.reporting.domain.models import Finding, ReportError


class Budget:
    def remaining(self):
        return 1.25


def test_public_cli_help_does_not_read_configuration_or_observe_host(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("help must not construct host adapters")

    monkeypatch.setattr(cli, "build", forbidden)
    monkeypatch.setattr(cli, "supervise", forbidden)
    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "never deletes" in result.stdout


def test_missing_required_configuration_denies_before_process_or_publisher(monkeypatch):
    for key in os.environ:
        if key.startswith("NODE_RETENTION_REPORT_"):
            monkeypatch.delenv(key)

    def forbidden(*args, **kwargs):
        pytest.fail("missing required data produced an observation side effect")

    monkeypatch.setattr(cli, "build", forbidden)
    monkeypatch.setattr(cli, "supervise", forbidden)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 2
    assert "job_id" in result.output
    assert "expected_seconds" in result.output


def finding(name="lane-old"):
    return Finding(
        kind="stale-tree-report",
        owner="lane",
        name=name,
        age_hours=7,
        allocated_bytes=4096,
        root_owned=False,
        device=1,
        inode=123,
    )


def publisher(tmp_path):
    return CanonicalPublisher(
        tmp_path / "publisher",
        tmp_path / "ledger",
        job_id="20261115T010000Z-123",
        owner="caller",
        host="worker",
        pid=123,
        jobs_root=tmp_path,
    )


def test_publication_uses_injected_canonical_executable_and_json_serialization(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(publisher_module.subprocess, "run", run)
    publisher(tmp_path).publish((finding('lane-"quoted'),), Budget())
    command, options = calls[0]
    assert command[:2] == ["/usr/bin/timeout", "--signal=KILL"]
    assert "--foreground" not in command
    assert command[3] == str(tmp_path / "publisher")
    assert command[4] == "append"
    assert "timeout" not in options, "Python must not kill the surviving native watchdog"
    extra = command[command.index("--extra-members") + 1]
    assert json.loads("{" + extra + "}")["reported_names"] == ['lane-"quoted']
    evidence = json.loads("{" + extra + "}")["resource_evidence"][0]
    assert evidence["allocated_bytes"] == 4096
    assert evidence["root_owned"] is False
    assert evidence["retention_authorized"] is False
    assert not (tmp_path / "ledger").exists()  # This adapter has no direct shared-ledger writer.


def test_downstream_failure_does_not_disclose_payload_or_return_success(monkeypatch, tmp_path):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(3, command, stderr="DO-NOT-DISCLOSE")

    monkeypatch.setattr(publisher_module.subprocess, "run", fail)
    with pytest.raises(ReportError) as caught:
        publisher(tmp_path).publish((finding(),), Budget())
    assert "DO-NOT-DISCLOSE" not in str(caught.value)
    assert "not complete" in str(caught.value)


def test_chunk_and_owner_invariants_fail_before_publisher(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid batch reached publisher")

    monkeypatch.setattr(publisher_module.subprocess, "run", forbidden)
    with pytest.raises(ReportError):
        publisher(tmp_path).publish((finding(),) * 5, Budget())


def test_original_deadline_and_retention_age_remain_configuration_owned(tmp_path):
    config = ReportSettings(
        job_id="20261115T010000Z-123",
        owner="caller",
        host="worker",
        pid=123,
        jobs_root=tmp_path,
        ledger=tmp_path / "ledger",
        publisher=tmp_path / "publisher",
        started_epoch=int(time.time()),
        expected_seconds=300,
        stale_hours=12,
    )
    assert config.original_deadline_epoch == config.started_epoch + 300
    assert config.stale_seconds == 12 * 3600
    with pytest.raises(ValueError, match="cannot extend"):
        ReportSettings(
            **config.model_dump(exclude={"phase_deadline_epoch"}),
            phase_deadline_epoch=config.original_deadline_epoch + 1,
        )


def test_domain_and_application_have_no_concrete_import_or_deletion_api():
    import ast

    root = Path(__file__).parents[2] / "src/node_retention/reporting"
    for directory in (root / "domain", root / "application"):
        for source in directory.glob("*.py"):
            parsed = ast.parse(source.read_text())
            imports = [node.module for node in ast.walk(parsed) if isinstance(node, ast.ImportFrom)]
            assert not any(name and ".adapters" in name for name in imports)
            calls = [
                node.func.attr
                for node in ast.walk(parsed)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ]
            assert not {"remove", "rmtree", "unlink", "kill", "terminate"}.intersection(calls)


def test_every_report_module_and_fixture_stays_below_modularity_ceiling():
    root = Path(__file__).parents[2]
    for directory in (root / "src/node_retention/reporting", root / "tests/reporting"):
        for source in directory.rglob("*"):
            if source.suffix in (".py", ".sh"):
                assert len(source.read_text().splitlines()) <= 1000, source


def test_identity_error_diagnostic_has_no_input_values_or_observation(monkeypatch, tmp_path):
    values = {
        "JOB_ID": "20261115T010000Z-999",
        "OWNER": "test",
        "HOST": "DO-NOT-DISCLOSE",
        "PID": "123",
        "JOBS_ROOT": str(tmp_path),
        "LEDGER": str(tmp_path / "ledger"),
        "PUBLISHER": str(tmp_path / "publisher"),
        "STARTED_EPOCH": str(int(time.time())),
        "EXPECTED_SECONDS": "300",
    }
    for name, value in values.items():
        monkeypatch.setenv("NODE_RETENTION_REPORT_" + name, value)
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 2
    assert "configuration" in result.output
    assert "DO-NOT-DISCLOSE" not in result.output
    assert not (tmp_path / "ledger").exists()
