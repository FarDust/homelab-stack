"""Retention of the tmpfs job trees: idle time, lane activity, 24 h ceiling, size cap, ledger note, dry run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from node_retention import cli
from node_retention.adapters.local import JsonlLedger
from node_retention.application.applying import Applier
from node_retention.application.planning import Planner, Ports
from node_retention.domain.errors import LedgerUnreadableError
from node_retention.domain.models import Category, Outcome
from node_retention.domain.rules import job_lanes, lane_of
from tests.fakes import (
    GIB,
    HOUR,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeJobs,
    FakeLedger,
    FakeProcs,
    FakePublisher,
    make_settings,
)

ROOT = "/dev/shm/agent-jobs"
MIN = 60.0
MB = 1024**2


def _row(event: str, job_id: str, who: str, pid: int = 500) -> dict[str, object]:
    return {"event": event, "id": job_id, "who": who, "pid": pid, "class": "cpu-heavy", "what": "x", "where": "/h"}


def _plan(tmp_path: Path, fs: FakeFs, rows=None, procs=None, docker=None, **kw: object):
    ledger = FakeLedger(rows or [])
    settings = make_settings(tmp_path, **kw)
    ports = Ports(
        fs=fs, procs=procs or FakeProcs(), docker=docker or FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger)
    )
    return settings, ports, ledger, Planner(settings, ports).build_shm()


def _paths(plan) -> set[str]:
    return {c.path for c in plan.candidates}


def _reasons(plan) -> dict[str, str]:
    return {s.path: s.reason for s in plan.skipped}


def test_idle_tree_of_a_finished_lane_is_collected_and_a_recent_one_kept(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/fix179-g1", 900 * MB, 3 * HOUR)
    fs.add(f"{ROOT}/fix179-g2", 900 * MB, 30 * MIN)
    rows = [_row("start", "a", "fix179"), _row("end", "a", "fix179")]
    _, _, _, plan = _plan(tmp_path, fs, rows)
    assert _paths(plan) == {f"{ROOT}/fix179-g1"}
    assert "lane fix179 has no job running" in plan.candidates[0].reason
    assert "used 30 min ago" in _reasons(plan)[f"{ROOT}/fix179-g2"]


def test_tree_of_a_lane_with_a_running_job_is_kept_until_24_hours_but_a_waiting_job_keeps_nothing(
    tmp_path: Path,
) -> None:
    # 2026-11-25: deferred jobs of one lane kept 1.6 GB of ended trees in RAM while swap was full. A job that
    # waits for admission holds no tree; only a running job keeps its lane's recent trees.
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/lira-g1", 100, 3 * HOUR)
    fs.add(f"{ROOT}/queued-g1", 100, 3 * HOUR)
    fs.add(f"{ROOT}/lira-g0", 100, 25 * HOUR)
    rows = [_row("start", "a", "lira", pid=7), _row("deferred", "b", "queued", pid=8)]
    _, _, _, plan = _plan(tmp_path, fs, rows, FakeProcs(alive={7, 8}))
    assert _paths(plan) == {f"{ROOT}/lira-g0", f"{ROOT}/queued-g1"}
    assert "has a job running" in _reasons(plan)[f"{ROOT}/lira-g1"]


def test_placeholder_lane_unspecified_owns_no_tree(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/unspecified-run-pr1-9", 100, 3 * HOUR)
    rows = [_row("start", "a", "unspecified", pid=7)]
    known, active = job_lanes(rows, lambda pid: True)
    assert "unspecified" not in known and "unspecified" not in active
    _, _, _, plan = _plan(tmp_path, fs, rows, FakeProcs(alive={7}))
    assert "no ledger lane owns it" in _reasons(plan)[f"{ROOT}/unspecified-run-pr1-9"]


def test_tree_whose_agent_job_creator_is_gone_goes_after_one_hour(tmp_path: Path) -> None:
    # run.sh stamps a hand-made checkout with `.agent-job`; once run.sh is gone the checkout is a dead job's tree.
    fs = FakeFs(root_free=20 * GIB)
    for name, age in (("jra-d647e9b", 2 * HOUR), ("jra-fresh", 20 * MIN), ("jra-live", 5 * HOUR)):
        fs.add(f"{ROOT}/{name}", 100, age)
    fs.records[f"{ROOT}/jra-d647e9b/.agent-job"] = "who=pr201 id=x created=t\n900 123\n"
    fs.records[f"{ROOT}/jra-fresh/.agent-job"] = "who=pr201 id=y created=t\n901 123\n"
    fs.records[f"{ROOT}/jra-live/.agent-job"] = "who=pr201 id=z created=t\n902 123\n"
    rows = [_row("start", "z", "pr201", pid=902)]
    _, _, _, plan = _plan(tmp_path, fs, rows, FakeProcs(alive={902}))
    assert _paths(plan) == {f"{ROOT}/jra-d647e9b"}
    assert "creator pid 900" in plan.candidates[0].reason
    # the live creator's tree falls back to its lane (from the record): lane pr201 runs, so it stays
    assert "lane pr201 has a job running" in _reasons(plan)[f"{ROOT}/jra-live"]


def test_a_lane_whose_job_process_died_without_an_end_row_is_not_active(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/crashed-g1", 100, 3 * HOUR)
    _, _, _, plan = _plan(tmp_path, fs, [_row("start", "a", "crashed", pid=9)], FakeProcs(alive=set()))
    assert _paths(plan) == {f"{ROOT}/crashed-g1"}


def test_a_note_row_after_the_start_row_does_not_end_the_job() -> None:
    known, active = job_lanes([_row("start", "a", "x", 5), _row("note", "a", "x", 5)], lambda pid: True)
    assert known == {"x"} and active == {"x"}


def test_tree_in_use_by_a_process_or_container_is_never_collected(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    for name in ("cwd-g1", "mounted-g1", "free-g1"):
        fs.add(f"{ROOT}/{name}", 100, 30 * HOUR)
    procs = FakeProcs(open_paths={f"{ROOT}/cwd-g1/node_modules"})
    docker = FakeDocker(mounts={f"{ROOT}/mounted-g1/work"})
    _, _, _, plan = _plan(tmp_path, fs, None, procs, docker)
    assert _paths(plan) == {f"{ROOT}/free-g1"}


def test_tree_owned_by_a_running_ledger_job_is_never_collected(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/lira-g1", 100, 30 * HOUR)
    job = _row("start", "a", "lira", pid=7) | {"where": f"{ROOT}/lira-g1/check/tree"}
    _, _, _, plan = _plan(tmp_path, fs, [job], FakeProcs(alive={7}))
    assert _paths(plan) == set()
    assert "running job" in _reasons(plan)[f"{ROOT}/lira-g1"]


def test_pid_named_dirs_follow_the_liveness_of_their_pid(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/20261113T021820Z-111", 100, 5 * HOUR)
    fs.add(f"{ROOT}/20261113T021820Z-222", 100, 40 * HOUR)
    _, _, _, plan = _plan(tmp_path, fs, None, FakeProcs(alive={222}))
    assert _paths(plan) == {f"{ROOT}/20261113T021820Z-111"}


def test_cap_evicts_the_oldest_idle_trees_first_and_stops_at_the_cap(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    # Five active-lane trees of 2 GiB (10 GiB) against a cap of 8 GiB: only the oldest needed one goes.
    ages = {"a": 100, "b": 90, "c": 80, "d": 70, "e": 60}
    for lane, age in ages.items():
        fs.add(f"{ROOT}/l{lane}-g1", 2 * GIB, age * MIN)
    rows = [_row("start", f"id{lane}", f"l{lane}", pid=7) for lane in ages]
    _, _, _, plan = _plan(tmp_path, fs, rows, FakeProcs(alive={7}))
    assert _paths(plan) == {f"{ROOT}/la-g1"}
    assert "cap 8 GiB" in plan.candidates[0].reason
    assert all(c.category is Category.SHM for c in plan.candidates)


def test_cap_never_evicts_a_tree_in_use_or_touched_in_the_last_minutes(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/open-g1", 5 * GIB, 100 * MIN)  # oldest, but a process uses it
    fs.add(f"{ROOT}/fresh-g1", 5 * GIB, 5 * MIN)  # touched 5 minutes ago
    fs.add(f"{ROOT}/lane-g1", 2 * GIB, 60 * MIN)
    rows = [_row("start", f"id{lane}", lane, pid=7) for lane in ("open", "fresh", "lane")]
    procs = FakeProcs(open_paths={f"{ROOT}/open-g1/x"}, alive={7})
    _, _, _, plan = _plan(tmp_path, fs, rows, procs)
    assert _paths(plan) == {f"{ROOT}/lane-g1"}


def test_cap_leaves_alive_pid_dirs_alone(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/20261113T021820Z-222", 9 * GIB, 100 * MIN)
    _, _, _, plan = _plan(tmp_path, fs, None, FakeProcs(alive={222}))
    assert _paths(plan) == set()


def test_unreadable_ledger_fails_closed_for_trees_too(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/old-g1", 100, 3 * HOUR)
    ledger = FakeLedger()
    ledger.unreadable = True
    settings = make_settings(tmp_path)
    ports = Ports(fs=fs, procs=FakeProcs(), docker=FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger))
    with pytest.raises(LedgerUnreadableError):
        Planner(settings, ports).build_shm()
    assert fs.removed == []


def test_lane_of_uses_the_longest_known_lane_prefix() -> None:
    assert lane_of("gpx173-rel0590-g1", {"gpx173", "gpx173-rel0590", "lira"}) == "gpx173-rel0590"
    assert lane_of("other-g1", {"lira"}) is None


def test_apply_writes_a_ledger_note_with_the_manifest_of_every_removed_tree(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/fix179-g1", 900 * MB, 3 * HOUR)
    rows = [_row("end", "a", "fix179")]
    settings, ports, _, plan = _plan(tmp_path, fs, rows)
    out = FakeLedger()
    manifest = Applier(settings, ports, out, FakePublisher()).apply(plan, "run1", 42, what="retention-shm-gc")
    assert fs.removed == [f"{ROOT}/fix179-g1"]
    assert [e.outcome for e in manifest.entries] == [Outcome.DELETED]
    events = [(r["event"], r["what"]) for r in out.rows]
    assert events[0] == ("start", "retention-shm-gc") and events[1] == ("end", "retention-shm-gc")
    note = out.rows[-1]
    assert note["event"] == "note" and note["kind"] == "tree-gc" and note["id"] == "run1-tree-gc"
    assert note["gc_freed_mb"] == 900 and str(note["manifest"]).endswith("manifest-run1.json")
    (item,) = note["gc_removed"]
    assert item["tree"] == f"{ROOT}/fix179-g1" and item["mb"] == 900 and item["age_min"] == 180
    assert "no job running" in item["reason"]


def test_apply_without_removals_writes_no_note(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    settings, ports, _, plan = _plan(tmp_path, fs)
    out = FakeLedger()
    Applier(settings, ports, out, FakePublisher()).apply(plan, "run2", 42)
    assert [r["event"] for r in out.rows] == ["start", "end"]


def _cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fs: FakeFs, rows, alive=None) -> FakeLedger:
    ledger = FakeLedger(rows)
    settings = make_settings(tmp_path)
    ports = Ports(fs=fs, procs=FakeProcs(alive=alive), docker=FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger))
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda s: ports)
    monkeypatch.setattr(cli, "TextfilePublisher", lambda directory, image: FakePublisher())
    appended = FakeLedger()
    monkeypatch.setattr(cli, "JsonlLedger", lambda path, **kw: appended)
    return appended


def test_shm_gc_dry_run_prints_the_plan_and_removes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/fix179-g1", 900 * MB, 3 * HOUR)
    appended = _cli(monkeypatch, tmp_path, fs, [_row("end", "a", "fix179")])
    result = CliRunner().invoke(cli.app, ["shm-gc", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert fs.removed == [] and appended.rows == []
    assert f"{ROOT}/fix179-g1" in result.stdout


def test_shm_gc_removes_idle_trees_of_finished_lanes_and_keeps_active_lanes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/fix179-g1", 900 * MB, 3 * HOUR)
    fs.add(f"{ROOT}/lira-g1", 900 * MB, 3 * HOUR)
    rows = [_row("end", "a", "fix179"), _row("start", "b", "lira", pid=9)]
    appended = _cli(monkeypatch, tmp_path, fs, rows, alive={9})
    result = CliRunner().invoke(cli.app, ["shm-gc"])
    assert result.exit_code == 0, result.output
    assert fs.removed == [f"{ROOT}/fix179-g1"]
    assert any(r["event"] == "note" for r in appended.rows)


def test_jsonl_ledger_skips_old_malformed_rows_but_fails_closed_on_recent_or_undated_ones(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    old = '{"ts":"2020-01-01T00:00:00Z","event":"end","id":"a","tree_mb":,"result":"exit=1"}'
    good = '{"ts":"2020-01-01T00:00:01Z","event":"end","id":"b"}'
    path.write_text(f"{old}\n{good}\n", encoding="utf-8")
    tolerant = JsonlLedger(path, malformed_tolerance_s=48 * 3600)
    assert tolerant.rows() == [{"ts": "2020-01-01T00:00:01Z", "event": "end", "id": "b"}]
    assert tolerant.skipped_lines == [1]
    with pytest.raises(LedgerUnreadableError, match="line 1"):
        JsonlLedger(path).rows()  # strict by default
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(f'{{"ts":"{now}","event":"start","tree_mb":,}}\n', encoding="utf-8")
    with pytest.raises(LedgerUnreadableError, match="line 1"):
        JsonlLedger(path, malformed_tolerance_s=48 * 3600).rows()
    path.write_text('{"event":"start","tree_mb":,}\n', encoding="utf-8")
    with pytest.raises(LedgerUnreadableError, match="line 1"):
        JsonlLedger(path, malformed_tolerance_s=48 * 3600).rows()


def test_tree_with_no_ledger_lane_is_kept_until_the_24_hour_ceiling(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/handmade-g1", 100, 3 * HOUR)
    fs.add(f"{ROOT}/handmade-g0", 100, 26 * HOUR)
    _, _, _, plan = _plan(tmp_path, fs, [_row("end", "a", "other")])
    assert _paths(plan) == {f"{ROOT}/handmade-g0"}
    assert "no ledger lane owns it" in _reasons(plan)[f"{ROOT}/handmade-g1"]


def test_cap_takes_trees_of_finished_lanes_before_trees_of_active_lanes(tmp_path: Path) -> None:
    fs = FakeFs(root_free=20 * GIB)
    fs.add(f"{ROOT}/busy-g1", 5 * GIB, 100 * MIN)  # older, but its lane runs a job
    fs.add(f"{ROOT}/done-g1", 5 * GIB, 60 * MIN)  # newer, its lane finished (idle under 120 min)
    rows = [_row("start", "a", "busy", pid=7), _row("end", "b", "done")]
    _, _, _, plan = _plan(tmp_path, fs, rows, FakeProcs(alive={7}))
    assert _paths(plan) == {f"{ROOT}/done-g1"}


def test_ledger_tolerance_comes_from_the_settings(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, ledger_malformed_tolerance_hours=1.0)
    ledger = cli._job_ledger(settings)
    assert ledger._tolerance_s == 3600.0


def test_guard_exits_1_when_shm_gc_fails_but_still_checks_the_root_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fs = FakeFs(root_free=20 * GIB)
    ledger = FakeLedger()
    ledger.unreadable = True
    settings = make_settings(tmp_path)
    ports = Ports(fs=fs, procs=FakeProcs(), docker=FakeDocker(), clock=FakeClock(), jobs=FakeJobs(ledger))
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda s: ports)
    monkeypatch.setattr(cli, "TextfilePublisher", lambda directory, image: FakePublisher())
    result = CliRunner().invoke(cli.app, ["guard"])
    assert result.exit_code == 1
    assert "nothing to do" in result.output
