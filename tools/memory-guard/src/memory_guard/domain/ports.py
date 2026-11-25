"""Ports the use case depends on."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memory_guard.domain.models import Attribution, GuardState, LoadedModel, MemorySample, ProcessUsage, ReclaimRecord


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

    def eligible(self, consecutive_low: int) -> bool:
        """True when the policy guards (enabled, sustained samples, interval, hourly cap) would allow a drop now."""
        ...

    def last_summary(self) -> str | None: ...


class GpuMemoryProbe(Protocol):
    def dedicated_usage(self) -> int:
        """Host GPU dedicated memory in use, summed over adapters. Raise ProbeError when the counter is unavailable."""
        ...


class ModelResidencyProbe(Protocol):
    def loaded_models(self) -> list[LoadedModel]:
        """Models Ollama holds in memory. Raise ProbeError when the endpoint is unset, down or answers badly."""
        ...


class CauseAttributor(Protocol):
    def __call__(self) -> Attribution:
        """Name why headroom is low. Never raises: an unreadable signal becomes an explicit 'cause unknown'."""
        ...
