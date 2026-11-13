from __future__ import annotations

import json
from pathlib import Path

import pytest

from node_retention.application.applying import Applier
from node_retention.application.metrics import render_metrics
from node_retention.application.planning import Planner, Ports
from node_retention.domain.models import Category, Outcome
from tests.fakes import (
    DAY,
    GIB,
    HOUR,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeLedger,
    FakeProcs,
    FakePublisher,
    make_settings,
)


def _planner(
    tmp_path: Path, fs: FakeFs, procs: FakeProcs | None = None, docker: FakeDocker | None = None, **kw: object
):
    settings = make_settings(tmp_path, **kw)
    ports = Ports(fs=fs, procs=procs or FakeProcs(), docker=docker or FakeDocker(), clock=FakeClock())
    return settings, ports, Planner(settings, ports)


def _paths(plan) -> set[str]:
    return {c.path for c in plan.candidates}


def test_evidence_older_than_14_days_is_planned_and_young_one_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-pr22-evidence", 700, 15 * DAY)
    fs.add("/h/ci/dashboard-pr30-evidence", 700, 2 * DAY)
    fs.add("/h/ci/jra/run-evidence-old", 300, 20 * DAY)
    fs.add("/h/ci/jra/run-evidence-new", 300, 3 * DAY)
    fs.add("/h/ci/scripts", 50, 90 * DAY)  # unidentified: never a candidate
    _, _, planner = _planner(tmp_path, fs)
    plan = planner.build()
    assert _paths(plan) == {"/h/ci/dashboard-pr22-evidence", "/h/ci/jra/run-evidence-old"}
    skipped = {s.path for s in plan.skipped}
    assert {"/h/ci/dashboard-pr30-evidence", "/h/ci/jra/run-evidence-new"} <= skipped
    assert "/h/ci/scripts" not in skipped | _paths(plan)


def test_open_or_mounted_paths_are_never_candidates(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-a", 10, 30 * DAY)
    fs.add("/h/ci/dashboard-b", 10, 30 * DAY)
    fs.add("/h/ci/dashboard-c", 10, 30 * DAY)
    procs = FakeProcs(open_paths={"/h/ci/dashboard-a/deep/file.log"})
    docker = FakeDocker(mounts={"/h/ci/dashboard-b"})
    _, _, planner = _planner(tmp_path, fs, procs, docker)
    plan = planner.build()
    assert _paths(plan) == {"/h/ci/dashboard-c"}
    reasons = {s.path: s.reason for s in plan.skipped}
    assert reasons["/h/ci/dashboard-a"] == "open by a process"
    assert reasons["/h/ci/dashboard-b"] == "mounted into a container"


def test_protected_globs_win_over_age(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-x-evidence", 10, 30 * DAY)
    _, _, planner = _planner(tmp_path, fs, protected_globs=["*/dashboard-x-*"])
    plan = planner.build()
    assert plan.candidates == []
    assert plan.skipped[0].reason == "protected path"


def test_shm_job_dirs_follow_pid_liveness(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    root = "/dev/shm/agent-jobs"
    fs.add(f"{root}/20261113T021820Z-111", 100, 5 * HOUR)  # dead pid
    fs.add(f"{root}/20261113T021820Z-222", 100, 5 * HOUR)  # alive pid
    fs.add(f"{root}/pr75-abc", 100, 30 * HOUR)  # no pid, idle > 24 h
    fs.add(f"{root}/blank90-g13", 100, 1 * HOUR)  # no pid, recent
    _, _, planner = _planner(tmp_path, fs, FakeProcs(alive={222}))
    plan = planner.build()
    assert _paths(plan) == {f"{root}/20261113T021820Z-111", f"{root}/pr75-abc"}
    assert all(c.category is Category.SHM for c in plan.candidates)


def test_tmp_only_owned_and_idle_entries(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/tmp/old-mine", 10, 9 * DAY)
    fs.add("/tmp/new-mine", 10, 1 * DAY)
    fs.add("/tmp/old-root", 10, 9 * DAY, owned=False)
    _, _, planner = _planner(tmp_path, fs)
    assert _paths(planner.build()) == {"/tmp/old-mine"}


def test_tarballs_older_than_7_days(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/pr301-" + "a" * 40 + ".tar", 12, 8 * DAY)
    fs.add("/h/pr302-" + "b" * 40 + ".tar", 12, 1 * DAY)
    fs.add("/h/NVIDIA-Linux.run", 395, 200 * DAY)
    _, _, planner = _planner(tmp_path, fs)
    assert len(planner.build().candidates) == 1


def test_tool_caches_untouched_while_within_budget_and_floor(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/.cache/uv", 2 * GIB, 30 * DAY)
    fs.add("/h/.cache/pip", 1 * GIB, 30 * DAY)
    _, _, planner = _planner(tmp_path, fs)
    plan = planner.build()
    assert plan.candidates == [] and plan.budget_used_bytes == 3 * GIB


def test_tool_caches_pruned_oldest_first_over_budget_and_respect_24h_gate(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/.cache/uv", 4 * GIB, 10 * DAY)
    fs.add("/h/.cache/pip", 2 * GIB, 40 * DAY)
    fs.add("/h/.cache/playwright", 3 * GIB, 2 * HOUR)  # newest, inside the 24 h gate
    _, _, planner = _planner(tmp_path, fs)
    plan = planner.build()
    # 9 GiB used, budget 6: need 3 GiB; oldest first: pip (2) then uv (4); playwright is gated out.
    assert [c.path for c in plan.candidates] == ["/h/.cache/pip", "/h/.cache/uv"]
    assert "/h/.cache/playwright" in {s.path for s in plan.skipped} or plan.budget_used_bytes == 9 * GIB


def test_floor_violation_prunes_caches_even_within_budget(tmp_path: Path) -> None:
    fs = FakeFs(root_free=int(5.8 * GIB))
    fs.add("/h/.cache/uv", 2 * GIB, 10 * DAY)
    fs.add("/h/.cache/pip", 1 * GIB, 20 * DAY)
    _, _, planner = _planner(tmp_path, fs)
    plan = planner.build()
    assert plan.floor_violated
    assert next(c.path for c in plan.candidates) == "/h/.cache/pip"
    assert sum(c.size_bytes for c in plan.candidates) >= int(2.2 * GIB)


def test_docker_candidates_use_dangling_and_build_cache_only(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    _, _, planner = _planner(tmp_path, fs, docker=FakeDocker(dangling=5, cache=7))
    plan = planner.build()
    assert {c.action for c in plan.candidates} == {"docker_image_prune", "docker_builder_prune"}


def test_apply_writes_manifest_before_deleting_and_records_ledger_and_metrics(tmp_path: Path) -> None:
    fs = FakeFs(root_free=int(5.8 * GIB))
    fs.add("/h/ci/dashboard-old", 3 * GIB, 30 * DAY)
    settings, ports, planner = _planner(tmp_path, fs)
    ledger, pub = FakeLedger(), FakePublisher()
    plan = planner.build()
    manifest_seen: dict[str, object] = {}
    original_remove = fs.remove

    def spying_remove(path: str) -> None:
        mpath = settings.state_dir / "manifest-r1.json"
        manifest_seen["exists"] = mpath.exists()
        manifest_seen["body"] = json.loads(mpath.read_text())
        original_remove(path)

    fs.remove = spying_remove  # type: ignore[method-assign]
    manifest = Applier(settings, ports, ledger, pub).apply(plan, "r1", pid=42)
    assert manifest_seen["exists"] is True
    entry = manifest_seen["body"]["entries"][0]["candidate"]  # type: ignore[index]
    assert entry["path"] == "/h/ci/dashboard-old" and entry["size_bytes"] == 3 * GIB and entry["reason"]
    assert manifest.freed_bytes == 3 * GIB and manifest.entries[0].outcome is Outcome.DELETED
    assert [r["event"] for r in ledger.rows] == ["start", "end"]
    assert ledger.rows[1]["who"] == "retention" and ledger.rows[1]["freed_bytes"] == 3 * GIB
    prom = pub.files["node_retention.prom"]
    assert f'node_retention_last_run_freed_bytes{{host="node-a"}} {3 * GIB}' in prom
    assert 'node_retention_last_run_success{host="node-a"} 1' in prom


def test_apply_rechecks_open_files_just_before_deleting(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-old", 10, 30 * DAY)
    settings, ports, planner = _planner(tmp_path, fs)
    plan = planner.build()
    ports.procs.open.add("/h/ci/dashboard-old/x")  # type: ignore[attr-defined]
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "r2", pid=1)
    assert manifest.entries[0].outcome is Outcome.SKIPPED_OPEN and fs.removed == []


def test_failed_removal_is_recorded_and_flags_the_run_as_failed(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-a", 10, 30 * DAY)
    fs.add("/h/ci/dashboard-b", 10, 30 * DAY)
    fs.refuse_removal.add("/h/ci/dashboard-a")
    settings, ports, planner = _planner(tmp_path, fs)
    ledger, pub = FakeLedger(), FakePublisher()
    manifest = Applier(settings, ports, ledger, pub).apply(planner.build(), "r3", pid=1)
    outcomes = {e.candidate.path: e.outcome for e in manifest.entries}
    assert outcomes["/h/ci/dashboard-a"] is Outcome.FAILED
    assert outcomes["/h/ci/dashboard-b"] is Outcome.DELETED
    assert ledger.rows[-1]["result"] == "exit=1"
    assert 'node_retention_last_run_success{host="node-a"} 0' in pub.files["node_retention.prom"]


def test_guard_metrics_omit_run_gauges(tmp_path: Path) -> None:
    text = render_metrics(make_settings(tmp_path), free_bytes=9 * GIB, now=1000.0)
    assert "node_retention_root_free_bytes" in text and "last_run" not in text


@pytest.mark.parametrize("text,expected", [("6.298GB", 6_298_000_000), ("0B", 0), ("1.5GiB", int(1.5 * GIB))])
def test_docker_size_parsing(text: str, expected: int) -> None:
    from node_retention.adapters.docker_cli import parse_size

    assert parse_size(text) == expected
    with pytest.raises(ValueError):
        parse_size("none")


def test_old_evidence_that_was_read_in_the_last_24_hours_is_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-scanned", 10, 30 * DAY, read_age_s=2 * HOUR)
    fs.add("/h/ci/dashboard-quiet", 10, 30 * DAY, read_age_s=30 * HOUR)
    _, _, planner = _planner(tmp_path, fs)
    plan = planner.build()
    assert _paths(plan) == {"/h/ci/dashboard-quiet"}
    assert "used 2.0 h ago" in next(s.reason for s in plan.skipped if s.path.endswith("scanned"))


def test_dead_job_dir_read_minutes_ago_is_kept_one_hour_idle_window(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    root = "/dev/shm/agent-jobs"
    fs.add(f"{root}/20261113T021820Z-111", 100, 5 * HOUR, read_age_s=600)
    _, _, planner = _planner(tmp_path, fs)
    assert planner.build().candidates == []


def test_independent_file_caches_are_pruned_file_by_file_before_whole_units(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/t/node-compile-cache", 4 * GIB, 0)  # in active use: written just now
    fs.stale["/t/node-compile-cache"] = 3 * GIB
    fs.add("/h/.cache/pip", 4 * GIB, 30 * DAY)
    settings, ports, planner = _planner(tmp_path, fs, stale_file_units=[Path("/t/node-compile-cache")])
    plan = planner.build()
    # 8 GiB used, budget 6: the 3 GiB of stale files cover the need, so pip is untouched.
    assert [(c.category, c.path) for c in plan.candidates] == [(Category.STALE_CACHE_FILES, "/t/node-compile-cache")]
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "r4", pid=1)
    assert manifest.freed_bytes == 3 * GIB and fs.pruned_stale == ["/t/node-compile-cache"]
    assert fs.exists("/t/node-compile-cache") and fs.removed == []


def test_ci_scratch_children_are_removed_after_the_scratch_window(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci-agent/run-old.log", 5, 20 * DAY)
    fs.add("/h/ci-agent/run-new.log", 5, 3 * DAY)
    fs.add("/h/ci-agent/queue-archives", 150, 20 * DAY)  # live working directory of the queue
    _, _, planner = _planner(tmp_path, fs, ci_scratch_roots=[Path("/h/ci-agent")])
    plan = planner.build()
    assert _paths(plan) == {"/h/ci-agent/run-old.log"}
    assert {s.path: s.reason for s in plan.skipped}["/h/ci-agent/queue-archives"] == "protected path"


def test_parent_cwd_and_broad_parent_mounts_do_not_protect_a_child(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-old", 10, 30 * DAY)
    procs = FakeProcs(open_paths={"/h/ci", "/h"})  # a worker whose cwd is the parent directory
    docker = FakeDocker(mounts={"/", "/h", "/tmp"})  # monitoring containers bind-mounting broad host paths
    _, _, planner = _planner(tmp_path, fs, procs, docker)
    assert _paths(planner.build()) == {"/h/ci/dashboard-old"}


def test_permission_denied_falls_back_to_the_root_helper_and_verifies_the_result(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-rooty", 10, 30 * DAY)
    fs.refuse_removal.add("/h/ci/dashboard-rooty")
    docker = FakeDocker()
    docker.on_root_remove = lambda path: fs.nodes.pop(path)
    settings, ports, planner = _planner(tmp_path, fs, docker=docker)
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(planner.build(), "r5", pid=1)
    assert manifest.entries[0].outcome is Outcome.DELETED
    assert docker.calls == ["root-rm:/h/ci/dashboard-rooty"] and "root helper" in manifest.entries[0].detail


def test_root_helper_that_leaves_the_path_behind_is_a_failure(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add("/h/ci/dashboard-stuck", 10, 30 * DAY)
    fs.refuse_removal.add("/h/ci/dashboard-stuck")
    settings, ports, planner = _planner(tmp_path, fs)  # the fake helper does nothing
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(planner.build(), "r6", pid=1)
    assert manifest.entries[0].outcome is Outcome.FAILED
