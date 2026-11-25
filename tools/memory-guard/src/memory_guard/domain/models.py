"""Pure value types and the pressure rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

GIB = 1024**3


class Condition(StrEnum):
    VIRTUAL = "free_virtual"
    RAM = "free_ram"


@dataclass(frozen=True)
class MemorySample:
    commit_used: int
    commit_limit: int
    free_ram: int
    nonpaged_pool: int

    @property
    def free_virtual(self) -> int:
        return self.commit_limit - self.commit_used


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    name: str
    private_bytes: int


@dataclass(frozen=True)
class Thresholds:
    min_free_virtual: int
    min_free_ram: int
    samples: int
    alert_interval: timedelta

    def breached(self, sample: MemorySample) -> dict[Condition, bool]:
        return {
            Condition.VIRTUAL: sample.free_virtual < self.min_free_virtual,
            Condition.RAM: sample.free_ram < self.min_free_ram,
        }


@dataclass
class ConditionState:
    consecutive: int = 0
    active: bool = False
    last_alert: datetime | None = None


@dataclass
class GuardState:
    conditions: dict[Condition, ConditionState] = field(
        default_factory=lambda: {c: ConditionState() for c in Condition}
    )


def gib(value: int) -> str:
    return f"{value / GIB:.2f} GiB"
