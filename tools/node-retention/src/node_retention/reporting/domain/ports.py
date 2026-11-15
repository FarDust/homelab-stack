"""Explicit ports for one read-only report; no deletion port exists."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from node_retention.reporting.domain.models import (
    Container,
    Finding,
    LedgerSnapshot,
    ProcessSnapshot,
    Tree,
    TreeEvidence,
)


class Clock(Protocol):
    def wall(self) -> float: ...
    def monotonic(self) -> float: ...


class Budget(Protocol):
    def remaining(self) -> float: ...


class Inventory(Protocol):
    def trees(self, budget: Budget) -> Iterable[Tree]: ...
    def evidence(self, tree: Tree, budget: Budget) -> TreeEvidence: ...


class Processes(Protocol):
    def snapshot(self, budget: Budget) -> ProcessSnapshot: ...


class Containers(Protocol):
    def snapshot(self, budget: Budget) -> tuple[Container, ...]: ...


class Ledger(Protocol):
    def snapshot(self, budget: Budget) -> LedgerSnapshot: ...


class Publisher(Protocol):
    def publish(self, findings: tuple[Finding, ...], budget: Budget) -> None: ...
