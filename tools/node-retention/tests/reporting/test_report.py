"""Characterize retained owner/idle/live/dedup rules without any deletion API."""

from dataclasses import dataclass, field

from node_retention.reporting.application.report import Reporter
from node_retention.reporting.domain.models import (
    Container,
    LedgerSnapshot,
    ProcessSnapshot,
    ReportError,
    ReportStatus,
    Tree,
    TreeEvidence,
    path_ancestors,
)


def make_tree(path, name, owner):
    return Tree(path, name, owner, 1, 123)


@dataclass
class Clock:
    now: float = 100_000
    ticks: float = 0

    def wall(self):
        return self.now

    def monotonic(self):
        return self.ticks


@dataclass
class Inventory:
    entries: list[Tree]
    clock: Clock
    advance: float = 0
    evidence_calls: list[str] = field(default_factory=list)

    def trees(self, budget):
        for tree in self.entries:
            self.clock.ticks += self.advance
            yield tree

    def evidence(self, tree, budget):
        budget.remaining()
        self.evidence_calls.append(tree.name)
        return TreeEvidence(4096, 1000, False, 1, 123)


@dataclass
class Processes:
    snapshot_value: ProcessSnapshot = field(default_factory=lambda: ProcessSnapshot(frozenset(), 17, 0))
    calls: int = 0

    def snapshot(self, budget):
        budget.remaining()
        self.calls += 1
        return self.snapshot_value


@dataclass
class Containers:
    entries: tuple[Container, ...] = ()
    calls: int = 0

    def snapshot(self, budget):
        budget.remaining()
        self.calls += 1
        return self.entries


@dataclass
class Ledger:
    value: LedgerSnapshot = field(
        default_factory=lambda: LedgerSnapshot(
            frozenset({"lane", "lane-long"}), frozenset(), frozenset(), 100_300, 0, frozenset(), ()
        )
    )

    def snapshot(self, budget):
        budget.remaining()
        return self.value


@dataclass
class Publisher:
    notes: list[tuple] = field(default_factory=list)
    fail: bool = False

    def publish(self, findings, budget):
        budget.remaining()
        if self.fail:
            raise ReportError("canonical publisher write failed")
        self.notes.append(findings)


def setup(entries):
    clock = Clock()
    inventory = Inventory(entries, clock)
    procs, containers, ledger, publisher = Processes(), Containers(), Ledger(), Publisher()
    reporter = Reporter(clock, inventory, procs, containers, ledger, publisher)
    return reporter, clock, inventory, procs, containers, ledger, publisher


def run(reporter, **kw):
    return reporter.run(deadline_epoch=100_300, maximum_seconds=5, stale_seconds=21_600, **kw)


def test_large_inventory_takes_one_process_and_container_snapshot():
    reporter, _, _, procs, containers, _, publisher = setup(
        [make_tree(f"/scratch/lane-g{i:07x}", f"lane-g{i:07x}", None) for i in range(10_000)]
    )
    result = run(reporter)
    assert result.status == ReportStatus.COMPLETE
    assert len(result.findings) == 10_000
    assert procs.calls == containers.calls == 1
    assert len(publisher.notes) == 10_000
    assert all(len(note) <= 2 for note in publisher.notes)


def test_live_ancestors_mounted_tree_dedup_unknown_and_longest_owner_are_preserved():
    entries = [
        make_tree("/scratch/" + name, name, owner)
        for name, owner in [
            ("lane-live", None),
            ("lane-mounted", None),
            ("lane-old", None),
            ("unknown", None),
            ("lane-long-gabcdef0", None),
            ("lane-marker", "marker"),
        ]
    ]
    reporter, _, inventory, procs, containers, ledger, _ = setup(entries)
    procs.snapshot_value = ProcessSnapshot(path_ancestors("/scratch/lane-live/work/file"), 1, 0)
    containers.entries = (Container("application", "lane", 99_999, ("/scratch/lane-mounted/work",)),)
    ledger.value = LedgerSnapshot(
        frozenset({"lane", "lane-long"}), frozenset({"lane-old"}), frozenset(), 100_300, 0, frozenset(), ()
    )
    result = run(reporter)
    assert {(f.name, f.owner) for f in result.findings} == {
        ("lane-long-gabcdef0", "lane-long"),
        ("lane-marker", "marker"),
    }
    assert inventory.evidence_calls == ["lane-long-gabcdef0", "lane-marker"]


def test_deadline_reports_partial_and_never_claims_remaining_inventory_complete():
    reporter, _, inventory, procs, _, _, publisher = setup(
        [make_tree(f"/scratch/lane-{i}", f"lane-{i}", None) for i in range(10_000)]
    )
    inventory.advance = 0.6
    result = run(reporter)
    assert result.status == ReportStatus.PARTIAL
    assert result.trees_examined < 10
    assert procs.calls == 1
    assert len(publisher.notes) == result.published_notes > 0
    assert [note[0].name for note in publisher.notes] == [finding.name for finding in result.findings]
    assert "whole-report deadline" in result.reasons[0]


def test_inaccessible_processes_preserve_unknown_and_publish_nothing():
    reporter, _, inventory, procs, _, _, publisher = setup([make_tree("/scratch/lane-x", "lane-x", None)])
    procs.snapshot_value = ProcessSnapshot(frozenset(), 1, 1)
    result = run(reporter)
    assert result.status == ReportStatus.UNKNOWN
    assert inventory.evidence_calls == []
    assert publisher.notes == []


def test_publisher_failure_is_explicit_and_cannot_report_success():
    reporter, _, _, _, _, _, publisher = setup([make_tree("/scratch/lane-x", "lane-x", None)])
    publisher.fail = True
    result = run(reporter)
    assert result.status == ReportStatus.UNKNOWN
    assert result.published_notes == 0
    assert result.reasons == ("canonical publisher write failed",)


def test_later_tree_error_preserves_earlier_published_finding():
    reporter, _, inventory, _, _, _, publisher = setup(
        [make_tree("/scratch/lane-first", "lane-first", None), make_tree("/scratch/lane-bad", "lane-bad", None)]
    )
    original = inventory.evidence

    def evidence(tree, budget):
        if tree.name == "lane-bad":
            assert [note[0].name for note in publisher.notes] == ["lane-first"]
            raise ReportError("tree evidence unavailable")
        return original(tree, budget)

    inventory.evidence = evidence
    result = run(reporter)
    assert result.status == ReportStatus.PARTIAL
    assert result.published_notes == 1
    assert result.reasons == ("tree evidence unavailable",)
    assert [f.name for f in result.findings] == ["lane-first"]


def test_later_publisher_failure_keeps_prior_receipt_and_reports_failure():
    reporter, _, _, _, _, _, publisher = setup(
        [make_tree("/scratch/lane-first", "lane-first", None), make_tree("/scratch/lane-second", "lane-second", None)]
    )
    original = publisher.publish

    def publish(findings, budget):
        if publisher.notes:
            raise ReportError("second publication failed")
        original(findings, budget)

    publisher.publish = publish
    result = run(reporter)
    assert result.status == ReportStatus.PARTIAL
    assert result.published_notes == 1
    assert result.reasons == ("second publication failed",)
    assert [note[0].name for note in publisher.notes] == ["lane-first"]


def test_container_is_published_before_tree_traversal_expires():
    reporter, _, inventory, _, containers, _, publisher = setup([make_tree("/scratch/lane-old", "lane-old", None)])
    containers.entries = (Container("jt-old", None, 1000, ()),)
    inventory.advance = 5
    result = run(reporter)
    assert result.status == ReportStatus.PARTIAL
    assert result.published_notes == 1
    assert [note[0].name for note in publisher.notes] == ["jt-old"]
    assert inventory.evidence_calls == []


def test_requested_deadline_cannot_extend_the_original_persisted_deadline():
    reporter, _, _, procs, _, ledger, publisher = setup([])
    ledger.value = LedgerSnapshot(frozenset(), frozenset(), frozenset(), 100_001, 0, frozenset(), ())
    result = run(reporter)
    assert result.status == ReportStatus.UNKNOWN
    assert procs.calls == 0
    assert publisher.notes == []


def test_unlabelled_gate_container_is_reported_unknown_other_names_are_preserved():
    reporter, _, _, _, containers, _, _ = setup([])
    containers.entries = (Container("jt-old", None, 1000, ()), Container("user-application", None, 1000, ()))
    result = run(reporter)
    assert [(f.name, f.owner) for f in result.findings] == [("jt-old", "unknown owner")]


def test_active_ledger_cache_is_protected_and_terminal_fact_is_not_retention_permission():
    reporter, _, inventory, _, _, ledger, _ = setup(
        [
            make_tree("/scratch/lane-active", "lane-active", "lane"),
            make_tree("/scratch/lane-terminal", "lane-terminal", "lane"),
        ]
    )
    ledger.value = LedgerSnapshot(
        frozenset({"lane"}),
        frozenset(),
        frozenset(),
        100_300,
        0,
        frozenset({"/scratch/lane-active/cache"}),
        (("/scratch/lane-terminal/work", "synthetic-terminal-job"),),
    )
    result = run(reporter)
    assert inventory.evidence_calls == ["lane-terminal"]
    assert result.findings[0].lifecycle == "terminal-observed"
    assert result.findings[0].related_terminal_job_ids == ("synthetic-terminal-job",)
    assert result.findings[0].retention_authorized is False
    assert (result.findings[0].device, result.findings[0].inode) == (1, 123)


def test_parent_container_mount_protects_the_whole_candidate_subtree():
    reporter, _, inventory, _, containers, _, _ = setup([make_tree("/scratch/lane-old", "lane-old", "lane")])
    containers.entries = (Container("service", "lane", 99_999, ("/scratch",)),)
    assert run(reporter).findings == ()
    assert inventory.evidence_calls == []
