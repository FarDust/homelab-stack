"""The dangerous cases: running jobs, an unreadable ledger, symlink and mount escapes, sockets, mid-run use."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from node_retention import cli
from node_retention.adapters.local import JsonlLedger, LocalFileSystem
from node_retention.application.applying import Applier
from node_retention.application.planning import Planner, Ports
from node_retention.domain.errors import LedgerUnreadableError
from node_retention.domain.models import Outcome
from node_retention.domain.rules import running_job_paths
from tests.fakes import (
    DAY,
    GIB,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeJobs,
    FakeLedger,
    FakeProcs,
    FakePublisher,
    make_settings,
)

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="adapter targets Linux (/proc, sockets)")


def _setup(tmp_path: Path, fs: FakeFs, ledger: FakeLedger | None = None, procs: FakeProcs | None = None, **kw: object):
    ledger = ledger or FakeLedger()
    settings = make_settings(tmp_path, **kw)
    ports = Ports(fs=fs, procs=procs or FakeProcs(), docker=FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger))
    return settings, ports, ledger


def _job(event: str, job_id: str, pid: int, where_fs: str) -> dict[str, object]:
    return {"event": event, "id": job_id, "pid": pid, "who": "lane", "what": "x", "where_fs": where_fs}


def test_unreadable_ledger_fails_closed_before_any_candidate(tmp_path: Path) -> None:
    fs = FakeFs(root_free=2 * GIB)
    fs.add("/h/ci/dashboard-old", 3 * GIB, 30 * DAY)
    ledger = FakeLedger()
    ledger.unreadable = True
    settings, ports, _ = _setup(tmp_path, fs, ledger)
    with pytest.raises(LedgerUnreadableError):
        Planner(settings, ports).build()
    assert fs.removed == []


def test_ledger_that_turns_unreadable_mid_run_deletes_nothing_and_fails_the_run(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-a", 10, 30 * DAY)
    fs.add("/h/ci/dashboard-b", 10, 30 * DAY)
    settings, ports, ledger = _setup(tmp_path, fs)
    plan = Planner(settings, ports).build()
    ledger.unreadable = True
    pub = FakePublisher()
    manifest = Applier(settings, ports, FakeLedger(), pub).apply(plan, "r1", pid=1)
    assert fs.removed == []
    assert {e.outcome for e in manifest.entries} == {Outcome.FAILED}
    assert 'node_retention_last_run_success{host="node-a"} 0' in pub.files["node_retention_run.prom"]


def test_running_job_scratch_is_protected_in_both_directions(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/tmp/jt-m78", 10, 9 * DAY)  # the job works inside it
    fs.add("/dev/shm/agent-jobs/integrator6-g11", 10, 30 * 3600)  # the job's scratch is below it
    fs.add("/tmp/jt-finished", 10, 9 * DAY)  # the job ended
    fs.add("/tmp/jt-dead", 10, 9 * DAY)  # the job's pid is gone
    ledger = FakeLedger(
        [
            _job("start", "a", 100, "/tmp/jt-m78/repo"),
            _job("start", "b", 101, "/dev/shm/agent-jobs/integrator6-g11/chaos/tree"),
            _job("start", "c", 102, "/tmp/jt-finished"),
            _job("end", "c", 102, "/tmp/jt-finished"),
            _job("start", "d", 103, "/tmp/jt-dead"),
            _job("start", "e", 104, "/tmp"),  # names a whole root: does not block every /tmp entry
        ]
    )
    settings, ports, _ = _setup(tmp_path, fs, ledger, FakeProcs(alive={100, 101, 102, 104}))
    plan = Planner(settings, ports).build()
    assert {c.path for c in plan.candidates} == {"/tmp/jt-finished", "/tmp/jt-dead"}
    reasons = {s.path: s.reason for s in plan.skipped}
    assert "running job" in reasons["/tmp/jt-m78"]
    assert "running job" in reasons["/dev/shm/agent-jobs/integrator6-g11"]


def test_job_that_starts_after_the_plan_is_honoured_before_deleting(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/tmp/old-scratch", 10, 9 * DAY)
    settings, ports, ledger = _setup(tmp_path, fs, procs=FakeProcs(alive={7}))
    plan = Planner(settings, ports).build()
    ledger.job_rows.append(_job("deferred", "late", 7, "/tmp/old-scratch/work"))
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "r2", pid=1)
    assert manifest.entries[0].outcome is Outcome.SKIPPED_RUNNING_JOB and fs.removed == []


def test_symlinked_root_that_points_elsewhere_is_never_followed(tmp_path: Path) -> None:
    fs = FakeFs(root_free=2 * GIB)
    fs.add("/h/.cache/docker-data", 5 * GIB, 30 * DAY)
    fs.symlinks["/h/.cache"] = "/var/lib/docker"  # the cache root is a symlink into Docker's data
    settings, ports, _ = _setup(tmp_path, fs)
    plan = Planner(settings, ports).build()
    assert plan.candidates == []
    assert "symlink" in {s.path: s.reason for s in plan.skipped}["/h/.cache/docker-data"]


def test_symlinked_stale_file_unit_is_not_walked(tmp_path: Path) -> None:
    fs = FakeFs(root_free=2 * GIB)
    fs.add("/t/node-compile-cache", 4 * GIB, 0)
    fs.stale["/t/node-compile-cache"] = 3 * GIB
    fs.symlinks["/t/node-compile-cache"] = "/srv/game/world"
    settings, ports, _ = _setup(tmp_path, fs, stale_file_units=[Path("/t/node-compile-cache")])
    assert Planner(settings, ports).build().candidates == []


def test_tree_with_a_mount_point_or_a_socket_is_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/tmp/bind-holder", 10, 9 * DAY)
    fs.add("/tmp/dotnet-diagnostic-1-socket", 0, 9 * DAY)
    fs.add("/tmp/plain", 10, 9 * DAY)
    fs.mounts = {"/", "/tmp", "/tmp/bind-holder/data"}
    fs.sockets = {"/tmp/dotnet-diagnostic-1-socket"}
    settings, ports, _ = _setup(tmp_path, fs)
    plan = Planner(settings, ports).build()
    assert {c.path for c in plan.candidates} == {"/tmp/plain"}
    reasons = {s.path: s.reason for s in plan.skipped}
    assert "mount point" in reasons["/tmp/bind-holder"] and "socket" in reasons["/tmp/dotnet-diagnostic-1-socket"]


def test_file_touched_mid_run_is_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-old", 10, 30 * DAY)
    settings, ports, _ = _setup(tmp_path, fs)
    plan = Planner(settings, ports).build()
    fs.add("/h/ci/dashboard-old", 10, 30 * DAY, read_age_s=5)  # a job read it after the plan
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "r3", pid=1)
    assert manifest.entries[0].outcome is Outcome.SKIPPED_RECENT and fs.removed == []


@pytest.mark.parametrize("field", ["cache_units", "cache_roots", "ci_scratch_roots", "stale_file_units"])
@pytest.mark.parametrize("bad", ["/var/lib/docker/volumes", "/", "/etc", "/home/../var/lib/x", "/dev/sda1"])
def test_settings_refuse_roots_in_system_or_docker_trees(tmp_path: Path, field: str, bad: str) -> None:
    with pytest.raises(ValidationError, match="retention root"):
        make_settings(tmp_path, **{field: [Path(bad)]})


def test_running_job_paths_ignore_rows_without_id_and_keep_unknown_pids() -> None:
    rows: list[dict[str, object]] = [
        {"event": "note", "who": "x", "where_fs": "/tmp/note-only"},
        {"event": "start", "id": "j", "where_fs": "/tmp/no-pid"},
    ]
    assert running_job_paths(rows, lambda pid: False) == {"/tmp/no-pid"}


@linux_only
def test_jsonl_ledger_fails_closed_on_missing_or_malformed_rows_and_tolerates_a_torn_tail(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    with pytest.raises(LedgerUnreadableError):
        JsonlLedger(path).rows()
    path.write_text('{"event":"start","id":"a"}\nnot json\n{"event":"end","id":"a"}\n', encoding="utf-8")
    with pytest.raises(LedgerUnreadableError, match="line 2"):
        JsonlLedger(path).rows()
    path.write_text('{"event":"start","id":"a"}\n{"event":"en', encoding="utf-8")
    assert JsonlLedger(path).rows() == [{"event": "start", "id": "a"}]
    path.chmod(0)
    try:
        if os.geteuid() != 0:
            with pytest.raises(LedgerUnreadableError):
                JsonlLedger(path).rows()
    finally:
        path.chmod(0o644)


@linux_only
def test_local_fs_reports_sockets_mounts_and_symlinked_ancestors(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(tree / "s"))
        assert LocalFileSystem().stats(str(tree)).has_socket
    finally:
        sock.close()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("36 35 98:0 / /mnt/with\\040space rw - ext4 /dev/x rw\n", encoding="utf-8")
    assert LocalFileSystem().mount_points(str(mountinfo)) == {"/mnt/with space"}
    (tmp_path / "link").symlink_to(tree)
    assert LocalFileSystem().resolve(str(tmp_path / "link")) == str(tree.resolve())


def test_apply_that_aborts_still_publishes_a_failed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fs = FakeFs(root_free=20 * GIB)
    ledger = FakeLedger()
    ledger.unreadable = True
    pub = FakePublisher()
    settings = make_settings(tmp_path)
    ports = Ports(fs=fs, procs=FakeProcs(), docker=FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger))
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda s: ports)
    monkeypatch.setattr(cli, "TextfilePublisher", lambda directory, image: pub)
    result = CliRunner().invoke(cli.app, ["apply"])
    assert isinstance(result.exception, LedgerUnreadableError)
    assert 'node_retention_last_run_success{host="node-a"} 0' in pub.files["node_retention_run.prom"]
    assert fs.removed == []
