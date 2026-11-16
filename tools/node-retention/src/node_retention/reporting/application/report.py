"""One indexed snapshot and one whole-report budget, independent of concrete I/O."""

from __future__ import annotations

from dataclasses import dataclass

from node_retention.reporting.domain.models import (
    Finding,
    Outcome,
    ReportError,
    ReportExpired,
    ReportStatus,
    owner_for,
    path_ancestors,
)
from node_retention.reporting.domain.ports import Clock, Containers, Inventory, Ledger, Processes, Publisher


@dataclass
class Deadline:
    clock: Clock
    finish_monotonic: float

    @classmethod
    def start(cls, clock: Clock, deadline_epoch: float, maximum_seconds: float) -> Deadline:
        remaining = min(deadline_epoch - clock.wall(), maximum_seconds)
        if remaining <= 0:
            raise ReportExpired("original job deadline exhausted before reporting")
        return cls(clock, clock.monotonic() + remaining)

    def remaining(self) -> float:
        # Keep unknown evidence explicit; see docs/adr/ci_job_report_budget_adr.md.
        remaining = self.finish_monotonic - self.clock.monotonic()
        if remaining <= 0:
            raise ReportExpired("whole-report deadline exhausted; remaining inventory is unknown")
        return remaining


@dataclass(frozen=True)
class Reporter:
    clock: Clock
    inventory: Inventory
    processes: Processes
    containers: Containers
    ledger: Ledger
    publisher: Publisher

    def run(self, *, deadline_epoch: float, maximum_seconds: float, stale_seconds: float) -> Outcome:
        started = self.clock.monotonic()
        findings: list[Finding] = []
        reasons: list[str] = []
        examined = process_count = published = 0
        status = ReportStatus.COMPLETE
        try:
            budget = Deadline.start(self.clock, deadline_epoch, maximum_seconds)
            ledger = self.ledger.snapshot(budget)
            if deadline_epoch > ledger.job_deadline_epoch:
                raise ReportError("requested report deadline exceeds persisted original job deadline")
            if ledger.malformed_rows:
                reasons.append("unrelated malformed ledger rows retained; owner coverage may be incomplete")
                status = ReportStatus.PARTIAL
            processes = self.processes.snapshot(budget)
            process_count = processes.observed_processes
            if processes.inaccessible_processes:
                reasons.append("process snapshot incomplete; stale-tree safety evidence is unknown")
                status = ReportStatus.UNKNOWN
            containers = self.containers.snapshot(budget)
            mounted = frozenset(ancestor for c in containers for path in c.mounts for ancestor in path_ancestors(path))
            mount_sources = frozenset(path for container in containers for path in container.mounts)
            now = self.clock.wall()
            # Publish each verified finding before another observation can consume the budget.
            for container in containers:
                budget.remaining()
                if container.name in ledger.reported_containers:
                    continue
                owner = container.owner
                if owner is None:
                    if not container.name.startswith(("cif-", "jt-")):
                        continue
                    owner = "unknown owner"
                age = now - container.created_epoch
                if age >= stale_seconds:
                    finding = Finding(
                        kind="stale-container-report",
                        owner=owner,
                        name=container.name,
                        age_hours=age / 3600,
                        allocated_bytes=None,
                        root_owned=None,
                        lifecycle="running-observed",
                    )
                    findings.append(finding)
                    self.publisher.publish((finding,), budget)
                    published += 1
            active = frozenset(ancestor for path in ledger.active_paths for ancestor in path_ancestors(path))
            terminal: dict[str, set[str]] = {}
            for path, identity in ledger.terminal_paths:
                budget.remaining()
                for ancestor in path_ancestors(path):
                    terminal.setdefault(ancestor, set()).add(identity)
            trees = () if processes.inaccessible_processes else self.inventory.trees(budget)
            for tree in trees:
                budget.remaining()
                examined += 1
                owner = owner_for(tree, ledger.owners)
                if owner is None or tree.name in ledger.reported_trees:
                    continue
                if (
                    processes.holds(tree.path)
                    or tree.path in mounted
                    or tree.path in active
                    or path_ancestors(tree.path) & mount_sources
                ):
                    continue
                evidence = self.inventory.evidence(tree, budget)
                age = now - evidence.newest_mtime
                if age >= stale_seconds:
                    finding = Finding(
                        kind="stale-tree-report",
                        owner=owner,
                        name=tree.name,
                        age_hours=age / 3600,
                        allocated_bytes=evidence.allocated_bytes,
                        root_owned=evidence.root_owned,
                        device=evidence.device,
                        inode=evidence.inode,
                        lifecycle="terminal-observed" if tree.path in terminal else "unverified",
                        related_terminal_job_ids=tuple(sorted(terminal[tree.path])) if tree.path in terminal else (),
                    )
                    findings.append(finding)
                    self.publisher.publish((finding,), budget)
                    published += 1
            if status == ReportStatus.UNKNOWN and published:
                status = ReportStatus.PARTIAL  # Independently verified container reports remain useful.
            budget.remaining()
        except ReportExpired as error:
            status = ReportStatus.PARTIAL
            reasons.append(str(error))
        except ReportError as error:
            status = ReportStatus.PARTIAL if published else ReportStatus.UNKNOWN
            reasons.append(str(error))
        return Outcome(
            status=status,
            findings=tuple(findings),
            reasons=tuple(reasons),
            trees_examined=examined,
            processes_examined=process_count,
            published_notes=published,
            elapsed_seconds=self.clock.monotonic() - started,
        )
