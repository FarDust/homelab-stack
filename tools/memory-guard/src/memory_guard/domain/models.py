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


@dataclass(frozen=True)
class ReclaimSnapshot:
    """The three numbers recorded before and after a cache drop."""

    free_virtual: int
    free_ram: int
    vmmem_private: int


@dataclass(frozen=True)
class ReclaimRecord:
    at: datetime
    ok: bool
    before: ReclaimSnapshot
    after: ReclaimSnapshot | None
    error: str | None = None

    def summary(self) -> str:
        if not self.ok or self.after is None:
            return f"WSL cache drop at {self.at.isoformat()} FAILED: {self.error}"
        b, a = self.before, self.after
        return (
            f"WSL cache drop at {self.at.isoformat()}: free virtual {gib(b.free_virtual)} -> {gib(a.free_virtual)}, "
            f"free RAM {gib(b.free_ram)} -> {gib(a.free_ram)}, vmmemWSL {gib(b.vmmem_private)} -> {gib(a.vmmem_private)}"
        )


@dataclass(frozen=True)
class ReclaimPolicy:
    enabled: bool
    samples: int
    min_interval: timedelta
    max_per_hour: int
    settle_s: float


class CauseKind(StrEnum):
    GPU_MODEL = "gpu_model_resident"
    GPU_OTHER = "gpu_other_consumer"
    CPU_MODEL = "cpu_model_resident"
    PAGE_CACHE = "guest_page_cache"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LoadedModel:
    """One model Ollama holds in memory, from `GET /api/ps`."""

    name: str
    size: int
    size_vram: int
    expires_at: datetime


@dataclass(frozen=True)
class Attribution:
    kind: CauseKind
    text: str

    @property
    def line(self) -> str:
        """The alert line: an unknown cause already starts with its own label."""
        return self.text if self.kind is CauseKind.UNKNOWN else f"cause: {self.text}"

    @property
    def gpu_resident(self) -> bool:
        return self.kind is CauseKind.GPU_MODEL
