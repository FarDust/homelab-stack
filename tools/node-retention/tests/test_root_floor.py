"""Root floor on its own device and the step-down for ledger-ended CI job dirs (docs/adr/node_disk_retention_adr.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from node_retention.adapters.open_prs import OpenPrsFile
from node_retention.application.planning import Planner, Ports
from node_retention.domain.models import Category
from tests.fakes import (
    DAY,
    GIB,
    HOUR,
    NOW,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeJobs,
    FakeLedger,
    FakeProcs,
    FakePrs,
    make_settings,
)

CI = "/h/ci"
JRA = "/h/ci/jra"
TMP_DEV = 7


def _ts(age_s: float) -> str:
    return datetime.fromtimestamp(NOW - age_s, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(job_id: str, where: str, ended_age_s: float | None, what: str = "run.sh job check", pid: int = 500):
    rows: list[dict[str, object]] = [
        {
            "ts": _ts((ended_age_s or 0) + HOUR),
            "event": "start",
            "id": job_id,
            "who": "w",
            "pid": pid,
            "what": what,
            "where": where,
        },
    ]
    if ended_age_s is not None:
        rows.append(
            {
                "ts": _ts(ended_age_s),
                "event": "end",
                "id": job_id,
                "who": "w",
                "pid": pid,
                "what": what,
                "where": where,
                "result": "exit=0",
            }
        )
    return rows


def _plan(tmp_path: Path, fs: FakeFs, rows=(), procs=None, prs=None, docker=None, **kw: object):
    settings = make_settings(tmp_path, ci_job_roots=[Path(CI), Path(JRA)], **kw)
    ports = Ports(
        fs=fs,
        procs=procs or FakeProcs(),
        docker=docker or FakeDocker(),
        clock=FakeClock(),
        jobs=FakeJobs(FakeLedger(list(rows))),
        prs=prs or FakePrs(set()),
    )
    return Planner(settings, ports).build()


def _paths(plan, category: Category | None = None) -> list[str]:
    return [c.path for c in plan.candidates if category is None or c.category is category]


def test_docker_and_other_volume_candidates_never_count_toward_the_root_floor(tmp_path: Path) -> None:
    # 2026-11-25 frost-fang: 12 days under the floor while every apply freed ~0 on `/`, because the only
    # candidates were Docker images and build cache on a separate Docker volume and stale files on the `/tmp` volume.
    fs = FakeFs(root_free=int(4.9 * GIB))
    fs.devices["/tmp"] = TMP_DEV
    fs.add("/tmp/node-compile-cache", 1 * GIB, 1 * HOUR)
    fs.stale["/tmp/node-compile-cache"] = 300 * 2**20
    plan = _plan(
        tmp_path,
        fs,
        docker=FakeDocker(dangling=29 * GIB, cache=3 * GIB),
        stale_file_units=[Path("/tmp/node-compile-cache")],
    )
    assert {c.category for c in plan.candidates} >= {Category.DOCKER_IMAGES, Category.DOCKER_BUILD_CACHE}
    assert plan.root_reclaimable_bytes == 0
    assert plan.floor_violated and "short of the floor" in plan.floor_unmet_reason


def test_docker_on_the_root_filesystem_counts_toward_the_floor(tmp_path: Path) -> None:
    fs = FakeFs(root_free=7 * GIB)
    docker = FakeDocker(dangling=2 * GIB)
    docker.root_dir = "/srv/docker-on-root"
    plan = _plan(tmp_path, fs, docker=docker)
    assert plan.root_reclaimable_bytes == 2 * GIB and plan.floor_unmet_reason == ""


def test_step_down_takes_ledger_ended_job_dirs_oldest_first_and_stops_at_the_shortfall(tmp_path: Path) -> None:
    fs = FakeFs(root_free=int(7.5 * GIB))  # 0.5 GiB short
    fs.add(f"{JRA}/w186-old", 1 * GIB, 6 * DAY)
    fs.add(f"{CI}/bridge-v35", 1 * GIB, 4 * DAY)
    fs.add(f"{CI}/fresh-run", 1 * GIB, 2 * DAY)
    rows = [
        *_job("a", f"{JRA}/w186-old", 6 * DAY),
        *_job("b", f"{CI}/bridge-v35/tree", 4 * DAY),
        *_job("c", f"{CI}/fresh-run", 2 * DAY),
    ]
    plan = _plan(tmp_path, fs, rows)
    assert _paths(plan, Category.CI_JOB) == [f"{JRA}/w186-old"]
    assert plan.floor_step_days == 3.0 and plan.floor_unmet_reason == ""


def test_step_down_goes_to_one_day_only_when_three_days_is_not_enough(tmp_path: Path) -> None:
    fs = FakeFs(root_free=int(5.5 * GIB))  # 2.5 GiB short
    fs.add(f"{CI}/bridge-v35", 1 * GIB, 4 * DAY)
    fs.add(f"{CI}/fresh-run", 1 * GIB, 2 * DAY)
    fs.add(f"{CI}/today", 1 * GIB, 3 * HOUR)
    rows = [
        *_job("b", f"{CI}/bridge-v35", 4 * DAY),
        *_job("c", f"{CI}/fresh-run", 2 * DAY),
        *_job("d", f"{CI}/today", 3 * HOUR),
    ]
    plan = _plan(tmp_path, fs, rows)
    assert _paths(plan, Category.CI_JOB) == [f"{CI}/bridge-v35", f"{CI}/fresh-run"]
    assert plan.floor_step_days == 1.0
    assert "short of the floor" in plan.floor_unmet_reason


def test_no_step_down_while_the_floor_holds(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{CI}/bridge-v35", 1 * GIB, 4 * DAY)
    plan = _plan(tmp_path, fs, _job("b", f"{CI}/bridge-v35", 4 * DAY))
    assert _paths(plan, Category.CI_JOB) == [] and plan.floor_step_days is None


def test_step_down_keeps_running_unknown_reserved_and_off_root_dirs(tmp_path: Path) -> None:
    fs = FakeFs(root_free=1 * GIB)
    for name in ("running", "no-ledger", "tools", "other-dev", "open-job"):
        fs.add(f"{CI}/{name}", 1 * GIB, 5 * DAY)
    fs.devices[f"{CI}/other-dev"] = TMP_DEV
    rows = [
        # an old end row of an earlier job, then a newer job on the same dir that is still running
        *_job("r1", f"{CI}/running", 5 * DAY),
        {"ts": _ts(HOUR), "event": "start", "id": "r2", "who": "w", "pid": 77, "what": "x", "where": f"{CI}/running"},
        *_job("t", f"{CI}/tools/node22", 5 * DAY),
        *_job("o", f"{CI}/other-dev", 5 * DAY),
        *_job("j", f"{JRA}/x", 5 * DAY),  # names a child of jra, never jra itself as a child of ci
        {
            "ts": _ts(5 * DAY),
            "event": "deferred",
            "id": "q",
            "who": "w",
            "pid": 78,
            "what": "x",
            "where": f"{CI}/open-job",
        },
    ]
    plan = _plan(tmp_path, fs, rows, procs=FakeProcs(alive={77, 78}))
    assert _paths(plan, Category.CI_JOB) == []
    assert JRA not in _paths(plan)


def test_pr_tied_dirs_are_kept_while_the_pr_is_open_or_open_prs_are_unknown(tmp_path: Path) -> None:
    def build(prs: FakePrs):
        fs = FakeFs(root_free=1 * GIB)
        fs.add(f"{CI}/pr201-3c9b623", 1 * GIB, 5 * DAY)
        fs.add(f"{CI}/pr150-aaaaaaa", 1 * GIB, 5 * DAY)
        fs.add(f"{CI}/integrator28", 1 * GIB, 5 * DAY)
        rows = [
            *_job("a", f"{CI}/pr201-3c9b623", 5 * DAY),
            *_job("b", f"{CI}/pr150-aaaaaaa", 5 * DAY),
            *_job("c", f"{CI}/integrator28", 5 * DAY, what="merge gate for PR #382"),
        ]
        return set(_paths(_plan(tmp_path, fs, rows, prs=prs), Category.CI_JOB))

    assert build(FakePrs(None)) == set()
    assert build(FakePrs({201})) == {f"{CI}/pr150-aaaaaaa", f"{CI}/integrator28"}
    assert build(FakePrs({382})) == {f"{CI}/pr201-3c9b623", f"{CI}/pr150-aaaaaaa"}


def test_off_root_tool_cache_is_not_taken_for_the_floor_once_the_budget_holds(tmp_path: Path) -> None:
    fs = FakeFs(root_free=7 * GIB)
    fs.devices["/tmp"] = TMP_DEV
    fs.add("/tmp/node-compile-cache", 1 * GIB, 1 * HOUR)
    fs.stale["/tmp/node-compile-cache"] = 1 * GIB
    fs.add("/h/.cache/pip", 1 * GIB, 3 * DAY)
    plan = _plan(tmp_path, fs, stale_file_units=[Path("/tmp/node-compile-cache")])
    assert _paths(plan) == ["/h/.cache/pip"]
    assert plan.root_reclaimable_bytes == 1 * GIB


def test_open_prs_file_answers_unknown_when_missing_stale_or_malformed(tmp_path: Path) -> None:
    import os

    path = tmp_path / "open-prs.json"
    clock = FakeClock()
    assert OpenPrsFile(None, 3600, clock).numbers() is None
    assert OpenPrsFile(path, 3600, clock).numbers() is None
    path.write_text("[201, 382]", encoding="utf-8")
    os.utime(path, (NOW - 60, NOW - 60))
    assert OpenPrsFile(path, 3600, clock).numbers() == {201, 382}
    os.utime(path, (NOW - 7200, NOW - 7200))
    assert OpenPrsFile(path, 3600, clock).numbers() is None
    path.write_text('{"open": [1]}', encoding="utf-8")
    os.utime(path, (NOW - 60, NOW - 60))
    assert OpenPrsFile(path, 3600, clock).numbers() is None
    path.write_text("[]", encoding="utf-8")  # an empty list is a real answer: no PR is open
    os.utime(path, (NOW - 60, NOW - 60))
    assert OpenPrsFile(path, 3600, clock).numbers() == set()
    os.utime(path, (NOW + 3600, NOW + 3600))  # a writer with a clock in the future is not trusted
    assert OpenPrsFile(path, 3600, clock).numbers() is None


def test_symlinked_docker_data_root_is_judged_by_the_device_it_points_to(tmp_path: Path) -> None:
    fs = FakeFs(root_free=7 * GIB)
    fs.symlinks["/var/lib/docker"] = "/mnt/docker"
    fs.devices["/mnt/docker"] = TMP_DEV  # the link sits on `/`, the data does not
    plan = _plan(tmp_path, fs, docker=FakeDocker(dangling=2 * GIB))
    assert plan.root_reclaimable_bytes == 0 and "short of the floor" in plan.floor_unmet_reason


def test_step_down_takes_only_the_eligible_dir_among_the_kept_ones(tmp_path: Path) -> None:
    fs = FakeFs(root_free=int(7.5 * GIB))
    for name in ("eligible", "no-end-row", "ledger-never-names"):
        fs.add(f"{CI}/{name}", 1 * GIB, 5 * DAY)
    rows = [
        *_job("e", f"{CI}/eligible", 5 * DAY),
        # started 5 days ago, its process is gone, and no `end` row was ever written: not ended, so kept
        *_job("n", f"{CI}/no-end-row", None),
    ]
    plan = _plan(tmp_path, fs, rows)
    assert _paths(plan, Category.CI_JOB) == [f"{CI}/eligible"]


def test_step_down_keeps_children_of_the_evidence_store(tmp_path: Path) -> None:
    evidence = "/h/ci/evidence"
    fs = FakeFs(root_free=1 * GIB)
    fs.add(f"{evidence}/run-1", 1 * GIB, 5 * DAY)
    settings_roots = {"ci_scratch_roots": [Path(evidence)]}
    plan = _plan(tmp_path, fs, _job("x", f"{evidence}/run-1", 5 * DAY), **settings_roots)
    assert f"{evidence}/run-1" not in _paths(plan, Category.CI_JOB)
