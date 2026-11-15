"""Required evidence and downstream failures through actual package adapters."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

from node_retention.reporting.adapters.docker import DockerSnapshot
from node_retention.reporting.adapters.ledger import TailLedger
from node_retention.reporting.adapters.processes import IndexedProcesses
from node_retention.reporting.domain.models import ReportError


class Budget:
    def remaining(self):
        return 5.0


def test_ledger_uses_aware_original_start_and_preserves_unrelated_malformed_rows(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "not-json\n"
        + json.dumps(
            {
                "id": "job",
                "event": "start",
                "ts": "2026-11-15T01:00:00Z",
                "expected_s": 300,
                "who": "caller",
                "host": "worker",
                "pid": 123,
                "where": "/scratch/caller",
            }
        )
        + "\n"
        + json.dumps({"kind": "stale-tree-report", "who": "lane", "what": "reported [lane-old]"})
        + "\n"
    )
    snapshot = TailLedger(path, "job", tmp_path, owner="caller", host="worker", pid=123).snapshot(Budget())
    assert snapshot.job_deadline_epoch == datetime(2026, 11, 15, 1, 5, tzinfo=UTC).timestamp()
    assert snapshot.reported_trees == {"lane-old"}
    assert snapshot.malformed_rows == 1
    assert path.read_text().startswith("not-json\n")


@pytest.mark.parametrize(
    "row",
    [
        {"ts": "2026-11-15T01:00:00Z"},
        {"ts": "2026-11-15T01:00:00", "expected_s": 300},
        {"ts": "2026-11-15T01:00:00Z", "expected_s": True},
        {"ts": "2026-11-15T01:00:00Z", "expected_s": 0},
    ],
)
def test_invalid_original_deadline_never_defaults_to_a_new_budget(tmp_path, row):
    path = tmp_path / "ledger"
    path.write_text(
        json.dumps(
            {
                "id": "job",
                "event": "start",
                "who": "caller",
                "host": "worker",
                "pid": 123,
                "where": "/scratch/caller",
                **row,
            }
        )
        + "\n"
    )
    with pytest.raises(ReportError, match="persisted original deadline"):
        TailLedger(path, "job", tmp_path, owner="caller", host="worker", pid=123).snapshot(Budget())


def test_missing_or_outside_bounded_window_own_start_is_explicit(tmp_path):
    with pytest.raises(ReportError, match="unreadable"):
        TailLedger(tmp_path / "absent", "job", tmp_path, owner="caller", host="worker", pid=123).snapshot(Budget())
    path = tmp_path / "ledger"
    path.write_text(
        json.dumps(
            {
                "id": "job",
                "event": "start",
                "expected_s": 300,
                "ts": "2026-11-15T01:00:00Z",
                "who": "caller",
                "host": "worker",
                "pid": 123,
                "where": "/scratch/caller",
            }
        )
        + "\n"
        + ('{"event":"note"}\n' * 10)
    )
    with pytest.raises(ReportError, match="absent from bounded ledger"):
        TailLedger(path, "job", tmp_path, owner="caller", host="worker", pid=123, maximum_rows=2).snapshot(Budget())


def observation(**changes):
    return {
        "name": "/jt-test",
        "owner": None,
        "created": "2026-11-15T01:00:00.123456789Z",
        "mounts": [{"Type": "tmpfs"}, {"Type": "bind", "Source": "/scratch/lane/work"}],
        **changes,
    }


def test_docker_batches_inventory_and_understands_tmpfs_without_host_source(monkeypatch):
    calls = []

    def call(self, arguments, budget):
        calls.append(arguments)
        return "a\nb\n" if arguments == ["ps", "-q"] else "\n".join(json.dumps(observation()) for _ in range(2))

    monkeypatch.setattr(DockerSnapshot, "_call", call)
    result = DockerSnapshot().snapshot(Budget())
    assert len(calls) == 2
    assert calls[1][-2:] == ["a", "b"]
    assert result[0].mounts == ("/scratch/lane/work",)
    assert result[0].owner is None


@pytest.mark.parametrize(
    "changes",
    [
        {"created": "2026-11-15T01:00:00"},
        {"mounts": [{"Type": "bind"}]},
        {"mounts": [{"Type": "volume", "Source": "relative"}]},
        {"name": ""},
    ],
)
def test_malformed_required_container_evidence_fails_instead_of_reporting_absent(monkeypatch, changes):
    def call(self, arguments, budget):
        return "id\n" if arguments == ["ps", "-q"] else json.dumps(observation(**changes))

    monkeypatch.setattr(DockerSnapshot, "_call", call)
    with pytest.raises(ReportError, match="missing or malformed"):
        DockerSnapshot().snapshot(Budget())


class Process:
    def __init__(self, *, denied=False):
        self.denied = denied

    def oneshot(self):
        return nullcontext()

    def cwd(self):
        if self.denied:
            raise psutil.AccessDenied(123)
        return "/scratch/lane/work"

    def exe(self):
        return "/usr/bin/python"

    def cmdline(self):
        return ["python", "--project=/scratch/other/project", "--private-payload=DO-NOT-DISCLOSE"]


def test_process_snapshot_indexes_ancestors_once_and_retains_no_raw_arguments():
    calls = []
    adapter = IndexedProcesses(lambda: iter([Process(), Process(denied=True)]), lambda: calls.append("clear"))
    snapshot = adapter.snapshot(Budget())
    assert snapshot.holds("/scratch/lane")
    assert snapshot.holds("/scratch/other")
    assert snapshot.inaccessible_processes == 1
    assert snapshot.observed_processes == 2
    assert calls == ["clear"]
    assert "DO-NOT-DISCLOSE" not in repr(snapshot)


def test_ledger_notes_do_not_close_active_scope_and_terminal_rows_record_related_paths(tmp_path):
    rows = [
        {
            "id": "job",
            "event": "start",
            "ts": "2026-11-15T01:00:00Z",
            "expected_s": 300,
            "who": "caller",
            "host": "worker",
            "pid": 123,
            "where": "/scratch/caller/work",
        },
        {"id": "active", "event": "start", "where": "/scratch/lane-active/cache"},
        {"id": "active", "event": "note", "where": "/scratch/lane-active/cache"},
        {"id": "done", "event": "start", "where": "/scratch/lane-done/work"},
        {"id": "done", "event": "end", "where": "/scratch/lane-done/work"},
    ]
    path = tmp_path / "ledger"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = TailLedger(path, "job", Path("/scratch"), owner="caller", host="worker", pid=123).snapshot(Budget())
    assert "/scratch/lane-active/cache" in result.active_paths
    assert "/scratch/lane-done/work" not in result.active_paths
    assert ("/scratch/lane-done/work", "done") in result.terminal_paths


def test_malformed_own_evidence_cannot_reuse_earlier_valid_deadline(tmp_path):
    path = tmp_path / "ledger"
    start = {
        "id": "job",
        "event": "start",
        "ts": "2026-11-15T01:00:00Z",
        "expected_s": 300,
        "who": "caller",
        "host": "worker",
        "pid": 123,
        "where": "/scratch/caller",
    }
    original = json.dumps(start) + '\n{"id":"job","event":"start",broken}\n'
    path.write_text(original)
    with pytest.raises(ReportError, match="own job has malformed"):
        TailLedger(path, "job", tmp_path, owner="caller", host="worker", pid=123).snapshot(Budget())
    assert path.read_text() == original
