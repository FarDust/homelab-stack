"""Ports the use case depends on."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memory_guard.domain.models import GuardState, MemorySample, ProcessUsage, ReclaimRecord


class MemoryProbe(Protocol):
    def sample(self) -> MemorySample: ...


class ProcessLister(Protocol):
    def top_by_private_bytes(self, limit: int) -> tuple[list[ProcessUsage], int]:
        """Return the top processes and how many could not be read."""
        ...


class AlertSink(Protocol):
    def send(self, text: str) -> None:
        """Raise AlertError unless delivery is confirmed."""
        ...


class StateStore(Protocol):
    def load(self) -> GuardState: ...
    def save(self, state: GuardState) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class WslControl(Protocol):
    def is_running(self) -> bool:
        """True only when the distro is already running; never starts it. Raise ReclaimError if unknown."""
        ...

    def drop_cache(self) -> None:
        """Drop the guest page cache. Raise ReclaimError on failure or timeout."""
        ...


class VmmemProbe(Protocol):
    def private_bytes(self) -> int:
        """Private bytes of the WSL VM process. Raise ProbeError when the counter is missing."""
        ...


class ReclaimLog(Protocol):
    def recent(self, since: datetime) -> list[ReclaimRecord]: ...
    def append(self, record: ReclaimRecord) -> None: ...


class Reclaimer(Protocol):
    def __call__(self, sample: MemorySample, consecutive_low: int) -> ReclaimRecord | None:
        """Return the record of a drop that ran, None when a guard declined; raise GuardError on failure."""
        ...

    def last_summary(self) -> str | None: ...
