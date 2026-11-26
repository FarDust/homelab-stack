"""Retention of pytest owned-scratch volumes: dead pid, idle gate, size cap, unknown names, running jobs."""

from __future__ import annotations

from pathlib import Path

from node_retention.application.planning import Planner, Ports
from node_retention.domain.models import Category
from tests.fakes import (
    GIB,
    HOUR,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeJobs,
    FakeLedger,
    FakeProcs,
    make_settings,
)

ROOT = "/ps"
MIN = 60.0
MB = 1024**2


def _plan(tmp_path: Path, fs: FakeFs, rows=None, procs=None, full: bool = False, **kw: object):
    settings = make_settings(tmp_path, pytest_scratch_roots=[Path(ROOT)], **kw)
    ports = Ports(
        fs=fs,
        procs=procs or FakeProcs(),
        docker=FakeDocker(),
        clock=FakeClock(),
        jobs=FakeJobs(FakeLedger(rows or [])),
    )
    planner = Planner(settings, ports)
    return planner.build() if full else planner.build_shm()


def _paths(plan) -> set[str]:
    return {c.path for c in plan.candidates}


def _reasons(plan) -> dict[str, str]:
    return {s.path: s.reason for s in plan.skipped}


def test_dead_pid_run_idle_for_two_hours_goes_and_a_recent_one_waits(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/run-111-abc", 900 * MB, 3 * HOUR)
    fs.add(f"{ROOT}/run-222-def", 900 * MB, 30 * MIN)
    plan = _plan(tmp_path, fs)
    assert _paths(plan) == {f"{ROOT}/run-111-abc"}
    assert plan.candidates[0].category is Category.PYTEST_SCRATCH
    assert "pytest pid 111 is dead" in plan.candidates[0].reason
    assert "gate 2 h" in _reasons(plan)[f"{ROOT}/run-222-def"]


def test_run_of_a_live_pid_is_kept_whatever_its_age(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/run-333-ghi", 900 * MB, 48 * HOUR)
    plan = _plan(tmp_path, fs, procs=FakeProcs(alive={333}))
    assert _paths(plan) == set()
    assert "pytest pid 333 is alive" in _reasons(plan)[f"{ROOT}/run-333-ghi"]


def test_directories_with_other_names_are_never_candidates(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/lira-integrated-20261123-fg", GIB, 72 * HOUR)
    fs.add(f"{ROOT}/trust-venv-restore-20261123-g", 500 * MB, 72 * HOUR)
    fs.add(f"{ROOT}/lost+found", 16 * 1024, 72 * HOUR)
    plan = _plan(tmp_path, fs)
    assert _paths(plan) == set()
    assert all("owner unknown" in reason for reason in _reasons(plan).values())


def test_cap_takes_dead_runs_oldest_first_after_the_short_idle_gate(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/run-1-a", 2 * GIB, 100 * MIN)
    fs.add(f"{ROOT}/run-2-b", 2 * GIB, 60 * MIN)
    fs.add(f"{ROOT}/run-3-c", 2 * GIB, 5 * MIN)
    plan = _plan(tmp_path, fs)  # 6 GiB held, cap 4 GiB
    assert _paths(plan) == {f"{ROOT}/run-1-a"}
    assert "cap 4 GiB" in plan.candidates[0].reason
    assert f"{ROOT}/run-3-c" not in _paths(plan)


def test_run_named_by_a_running_ledger_job_is_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/run-444-jkl", 900 * MB, 5 * HOUR)
    rows = [
        {
            "event": "start",
            "id": "j1",
            "who": "lane",
            "pid": 444,
            "class": "cpu-heavy",
            "what": "x",
            "where": f"{ROOT}/run-444-jkl",
        }
    ]
    plan = _plan(tmp_path, fs, rows=rows, procs=FakeProcs(alive={444}))
    assert _paths(plan) == set()


def test_full_plan_also_judges_the_scratch_root(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/run-555-mno", 900 * MB, 4 * HOUR)
    plan = _plan(tmp_path, fs, full=True)
    assert f"{ROOT}/run-555-mno" in _paths(plan)


def test_scratch_root_is_an_allowed_deletion_target(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, pytest_scratch_roots=[Path(ROOT)])
    assert settings.is_allowed_target(f"{ROOT}/run-1-a")
    assert not settings.is_allowed_target(ROOT)
