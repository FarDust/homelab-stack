"""Typed ports the application depends on; adapters implement them, tests fake them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from node_memory_probe.domain.models import CgroupMemory, KernelSample, Mapping, ProcessBrief


class ProcessGone(Exception):
    """The process exited or its files vanished while it was being read."""


class ProcessUnreadable(Exception):
    """The kernel refused a read of the process (the probe lacks the privilege for it)."""


class JcmdError(Exception):
    """jcmd could not attach, timed out or answered with an error."""


class ProcSource(Protocol):
    def processes(self) -> list[ProcessBrief]: ...
    def mappings(self, pid: int) -> list[Mapping]: ...
    def cmdline(self, pid: int) -> list[str]: ...
    def stack_pointers(self, pid: int) -> list[int]: ...
    def read_bytes(self) -> dict[tuple[int, int], tuple[str, int]]:
        """(pid, start_ticks) -> (comm, cumulative storage read bytes) for every readable process."""
        ...


class KernelSource(Protocol):
    def sample(self) -> KernelSample: ...
    def cgroups(self) -> list[CgroupMemory]: ...
    def memory_limit(self, cgroup: str) -> int | None: ...


class JvmTool(Protocol):
    def run(self, brief: ProcessBrief, command: str) -> str: ...


class ContainerDirectory(Protocol):
    def names(self, container_ids: Sequence[str]) -> dict[str, str]: ...
    def resolve(self, names: Sequence[str]) -> dict[str, str]:
        """Container name -> full id for the running containers among `names`."""
        ...


class StateStore(Protocol):
    def load(self) -> dict[str, Any]: ...
    def save(self, state: dict[str, Any]) -> None: ...


class MetricsSink(Protocol):
    def publish(self, text: str) -> None: ...


class SnapshotStore(Protocol):
    def write(self, name: str, payload: dict[str, Any]) -> int: ...
    def enforce_retention(self, max_age_s: float, budget_bytes: int, now: float) -> tuple[int, int]:
        """Remove expired then oldest snapshots; returns (files removed, bytes kept)."""
        ...


class Clock(Protocol):
    def now(self) -> float: ...
    def monotonic(self) -> float: ...
