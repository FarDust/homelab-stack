"""Pure data types of the retention policy. No I/O lives in the domain package."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Category(StrEnum):
    EVIDENCE = "ci-evidence"
    TARBALL = "ci-tarball"
    TOOL_CACHE = "tool-cache"
    STALE_CACHE_FILES = "tool-cache-stale-files"
    CI_SCRATCH = "ci-scratch"
    TMP = "tmp-leftover"
    SHM = "shm-job"
    DOCKER_IMAGES = "docker-dangling-images"
    DOCKER_BUILD_CACHE = "docker-build-cache"


class TreeStats(BaseModel):
    """Size and recency of a path: newest file mtime and atime (directories and symlinks count by mtime only)."""

    model_config = ConfigDict(frozen=True)

    size_bytes: int = Field(ge=0)
    newest_mtime: float
    newest_atime: float
    # A Unix socket is a live IPC endpoint (tmux, ssh-agent, language servers): its holder is not visible as an
    # open path in /proc/<pid>/fd, so a tree that contains one is treated as in use.
    has_socket: bool = False

    @property
    def newest_ts(self) -> float:
        """Latest time the content was written or read."""
        return max(self.newest_mtime, self.newest_atime)


class StaleFiles(BaseModel):
    """Regular, singly linked files under a path that were neither read nor written since a cutoff."""

    model_config = ConfigDict(frozen=True)

    size_bytes: int = Field(ge=0)
    count: int = Field(ge=0)


class Candidate(BaseModel):
    """One deletion the policy proposes. `action` says how it is carried out."""

    model_config = ConfigDict(frozen=True)

    category: Category
    action: Literal["remove_path", "prune_stale_files", "docker_image_prune", "docker_builder_prune"]
    path: str
    size_bytes: int = Field(ge=0)
    age_seconds: float = Field(ge=0)
    min_idle_seconds: float = Field(default=0, ge=0)
    reason: str


class Skipped(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size_bytes: int
    reason: str


class Plan(BaseModel):
    host: str
    generated_at: float
    root_free_bytes: int
    root_floor_bytes: int
    budget_bytes: int
    budget_used_bytes: int
    floor_violated: bool
    candidates: list[Candidate]
    skipped: list[Skipped]

    @property
    def total_bytes(self) -> int:
        return sum(c.size_bytes for c in self.candidates)


class Outcome(StrEnum):
    DELETED = "deleted"
    SKIPPED_OPEN = "skipped-open-by-process"
    SKIPPED_MOUNTED = "skipped-mounted-by-container"
    SKIPPED_RECENT = "skipped-recently-used"
    SKIPPED_MISSING = "skipped-missing"
    SKIPPED_RUNNING_JOB = "skipped-running-job"
    SKIPPED_UNSAFE = "skipped-unsafe-path"
    FAILED = "failed"


class ManifestEntry(BaseModel):
    candidate: Candidate
    outcome: Outcome | None = None
    freed_bytes: int = 0
    detail: str = ""


class Manifest(BaseModel):
    host: str
    run_id: str
    started_at: float
    finished_at: float | None = None
    root_free_before: int
    root_free_after: int | None = None
    entries: list[ManifestEntry]

    @property
    def freed_bytes(self) -> int:
        return sum(e.freed_bytes for e in self.entries)
