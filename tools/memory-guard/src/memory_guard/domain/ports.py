"""Ports the use case depends on."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memory_guard.domain.models import GuardState, MemorySample, ProcessUsage


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
