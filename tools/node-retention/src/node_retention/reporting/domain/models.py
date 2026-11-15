"""Explicit reporting outcomes never authorize deletion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReportStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class ReportError(RuntimeError):
    """Required evidence could not be established."""


class ReportExpired(ReportError):
    """The original job or the smaller report budget has expired."""


class ReportCancelled(ReportError):
    def __init__(self, signal_number: int) -> None:
        super().__init__("report cancelled; owned worker cleanup requested")
        self.signal_number = signal_number
        self.worker_pid: int | None = None
        self.worker_termination_verified: bool | None = None


@dataclass(frozen=True)
class Tree:
    path: str
    name: str
    marker_owner: str | None
    device: int
    inode: int


@dataclass(frozen=True)
class TreeEvidence:
    allocated_bytes: int
    newest_mtime: float
    root_owned: bool
    device: int
    inode: int


@dataclass(frozen=True)
class Container:
    name: str
    owner: str | None
    created_epoch: float
    mounts: tuple[str, ...]


@dataclass(frozen=True)
class ProcessSnapshot:
    live_ancestors: frozenset[str]
    observed_processes: int
    inaccessible_processes: int

    def holds(self, path: str) -> bool:
        return path in self.live_ancestors


@dataclass(frozen=True)
class LedgerSnapshot:
    owners: frozenset[str]
    reported_trees: frozenset[str]
    reported_containers: frozenset[str]
    job_deadline_epoch: float
    malformed_rows: int
    active_paths: frozenset[str]
    terminal_paths: tuple[tuple[str, str], ...]


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["stale-tree-report", "stale-container-report"]
    owner: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    age_hours: float = Field(ge=0, allow_inf_nan=False)
    allocated_bytes: int | None = Field(ge=0, strict=True)
    root_owned: bool | None
    device: int | None = Field(default=None, ge=0, strict=True)
    inode: int | None = Field(default=None, gt=0, strict=True)
    lifecycle: Literal["unverified", "terminal-observed", "running-observed"] = "unverified"
    related_terminal_job_ids: tuple[str, ...] = ()
    retention_authorized: Literal[False] = False

    @model_validator(mode="after")
    def resource_evidence(self) -> Finding:
        if self.kind == "stale-tree-report" and (
            self.allocated_bytes is None or self.root_owned is None or self.device is None or self.inode is None
        ):
            raise ValueError("tree finding requires measured size, ownership and inode evidence")
        if self.kind == "stale-container-report" and (
            self.allocated_bytes is not None or self.root_owned is not None or self.lifecycle != "running-observed"
        ):
            raise ValueError("container report cannot claim unmeasured filesystem bytes or ownership")
        return self


class Outcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    status: ReportStatus
    findings: tuple[Finding, ...]
    reasons: tuple[str, ...]
    trees_examined: int = Field(ge=0, strict=True)
    processes_examined: int = Field(ge=0, strict=True)
    published_notes: int = Field(ge=0, strict=True)
    elapsed_seconds: float = Field(ge=0)
    worker_termination_verified: bool | None = None
    worker_pid: int | None = None


def path_ancestors(path: str) -> frozenset[str]:
    """Build the prefix index once, rather than scanning processes per tree."""
    parsed = PurePosixPath(path)
    if not parsed.is_absolute():
        return frozenset()
    return frozenset(str(p) for p in (parsed, *parsed.parents))


def owner_for(tree: Tree, known: frozenset[str]) -> str | None:
    if tree.marker_owner is not None:
        return tree.marker_owner if tree.marker_owner != "unspecified" else None
    matches = [owner for owner in known if owner != "unspecified" and tree.name.startswith(owner + "-")]
    return max(matches, key=len) if matches else None
