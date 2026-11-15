"""Blocking I/O, cancellation and invalid output cannot become successful receipts."""

import signal
import subprocess
import time

import pytest

from node_retention.reporting.adapters import supervisor
from node_retention.reporting.adapters.signals import cancellation_signals
from node_retention.reporting.config import ReportSettings
from node_retention.reporting.domain.models import Outcome, ReportCancelled, ReportStatus


def settings(tmp_path):
    return ReportSettings(
        job_id="20261115T010000Z-123",
        owner="test",
        host="worker",
        pid=123,
        jobs_root=tmp_path,
        ledger=tmp_path / "ledger",
        publisher=tmp_path / "publisher",
        started_epoch=int(time.time()),
        expected_seconds=30,
        maximum_seconds=0.5,
    )


class Child:
    pid = 987654

    def __init__(self, output=b"", *, blocked=False):
        self.output = output
        self.blocked = blocked
        self.killed = False
        self.returncode = None if blocked else 0

    def communicate(self, timeout):
        if self.blocked and not self.killed:
            raise subprocess.TimeoutExpired("owned-worker", timeout)
        self.returncode = -9 if self.killed else self.returncode
        return self.output, b""

    def poll(self):
        return self.returncode


def test_hard_timeout_kills_only_owned_group_and_verifies_termination(monkeypatch, tmp_path):
    child = Child(blocked=True)
    groups = []
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(supervisor.signal, "SIGKILL", 9, raising=False)

    def kill(pid, number):
        groups.append((pid, number))
        child.killed = True

    monkeypatch.setattr(supervisor.os, "killpg", kill, raising=False)
    outcome = supervisor.supervise(settings(tmp_path))
    assert outcome.status == ReportStatus.UNKNOWN
    assert outcome.worker_termination_verified is True
    assert groups == [(child.pid, 9)]
    assert "hard deadline" in outcome.reasons[0]


def test_bad_worker_json_or_success_exit_disagreement_is_unknown(monkeypatch, tmp_path):
    child = Child(b'{"status":"complete"}')
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **kw: child)
    outcome = supervisor.supervise(settings(tmp_path))
    assert outcome.status == ReportStatus.UNKNOWN
    assert "malformed" in outcome.reasons[0]
    child.output = (
        Outcome(
            status=ReportStatus.COMPLETE,
            findings=(),
            reasons=(),
            trees_examined=0,
            processes_examined=0,
            published_notes=0,
            elapsed_seconds=0,
        )
        .model_dump_json()
        .encode()
    )
    child.returncode = 7
    assert supervisor.supervise(settings(tmp_path)).status == ReportStatus.UNKNOWN


def test_expired_original_budget_starts_no_worker(monkeypatch, tmp_path):
    config = settings(tmp_path).model_copy(update={"started_epoch": int(time.time()) - 100, "expected_seconds": 1})

    def forbidden(*args, **kwargs):
        pytest.fail("expired report spawned a worker")

    monkeypatch.setattr(supervisor.subprocess, "Popen", forbidden)
    assert supervisor.supervise(config).status == ReportStatus.UNKNOWN


def test_term_during_creation_is_deferred_until_worker_can_be_cleaned(monkeypatch, tmp_path):
    child = Child(blocked=True)

    def create(*args, **kwargs):
        signal.raise_signal(signal.SIGTERM)
        return child

    monkeypatch.setattr(supervisor.subprocess, "Popen", create)
    monkeypatch.setattr(supervisor.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: setattr(child, "killed", True), raising=False)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(ReportCancelled), cancellation_signals():
        supervisor.supervise(settings(tmp_path))
    assert child.killed
    assert child.poll() == -9
    assert signal.getsignal(signal.SIGTERM) is before


def test_first_and_duplicate_term_during_cleanup_wait_for_owned_termination(monkeypatch, tmp_path):
    class TermDuringCleanup(Child):
        def communicate(self, timeout):
            if self.killed:
                signal.raise_signal(signal.SIGTERM)
                signal.raise_signal(signal.SIGTERM)
            return super().communicate(timeout)

    child = TermDuringCleanup(blocked=True)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(supervisor.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: setattr(child, "killed", True), raising=False)
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(ReportCancelled), cancellation_signals():
        supervisor.supervise(settings(tmp_path))
    assert child.poll() == -9
    assert signal.getsignal(signal.SIGTERM) is before


def test_worker_termination_that_cannot_be_verified_is_never_reported_clean(monkeypatch, tmp_path):
    child = Child(blocked=True)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(supervisor.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: None, raising=False)
    outcome = supervisor.supervise(settings(tmp_path))
    assert outcome.status == ReportStatus.UNKNOWN
    assert outcome.worker_termination_verified is False
    assert outcome.worker_pid == child.pid


def test_production_worker_uses_native_parent_guard_and_owned_session(monkeypatch, tmp_path):
    child = Child(
        Outcome(
            status=ReportStatus.COMPLETE,
            findings=(),
            reasons=(),
            trees_examined=0,
            processes_examined=0,
            published_notes=0,
            elapsed_seconds=0,
        )
        .model_dump_json()
        .encode()
    )
    calls = []

    def create(command, **options):
        calls.append((command, options))
        return child

    monkeypatch.setattr(supervisor.subprocess, "Popen", create)
    assert supervisor.supervise(settings(tmp_path)).status == ReportStatus.COMPLETE
    command, options = calls[0]
    assert command[:4] == ["/usr/bin/setpriv", "--pdeathsig", "KILL", "--"]
    assert command[-4:] == [supervisor.sys.executable, "-B", "-m", "node_retention.reporting.worker_entry"]
    assert options["start_new_session"] is True
    assert options["env"]["NODE_RETENTION_REPORT_CONTROLLER_PID"] == str(supervisor.os.getpid())
