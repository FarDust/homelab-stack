"""Typed thresholds and paths. Environment prefix NODE_RETENTION_, nested delimiter `__`."""

from __future__ import annotations

import posixpath
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from node_retention.domain.errors import UnsafeRootError
from node_retention.domain.rules import is_within

GIB = 1024**3

# System trees and Docker/Pterodactyl data are never pruned, whatever the configuration says. `/dev/shm`
# job scratch is the one allowed path under `/dev`.
FORBIDDEN_ROOTS = (
    "/bin",
    "/boot",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/sbin",
    "/sys",
    "/usr",
    "/var/lib",
    "/srv/docker",
    "/run",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NODE_RETENTION_", extra="forbid")

    host: str = Field(min_length=1)
    home: Path = Field(default_factory=Path.home)
    ci_root: Path
    tmp_root: Path = Path("/tmp")
    shm_jobs_root: Path = Path("/dev/shm/agent-jobs")
    state_dir: Path
    ledger_path: Path
    textfile_dir: Path = Path("/var/lib/node_exporter/textfile_collector")
    textfile_helper_image: str = "busybox:1.37"

    root_mount: Path = Path("/")
    root_free_floor_gib: float = 8.0
    cache_budget_gib: float = 6.0

    idle_hours: float = 24.0
    evidence_days: float = 14.0
    tarball_days: float = 7.0
    tmp_idle_days: float = 7.0
    shm_idle_hours: float = 24.0
    # Job dirs whose pid is dead: a dead owner is stronger evidence than the 24 h idle window.
    shm_dead_idle_hours: float = 1.0
    docker_build_cache_days: int = 7

    # Names under ci_root that are removed when older than evidence_days.
    evidence_globs: list[str] = ["dashboard-*", "*-evidence", "*.bundle", "er-release-*"]
    # Names under home that are git-archive tarballs of CI runs.
    tarball_globs: list[str] = ["pr[0-9]*-*.tar"]
    # Direct children of these directories are individually prunable tool caches.
    cache_roots: list[Path] = []
    # Single directories that are tool caches.
    cache_units: list[Path] = []
    # Caches whose files are independent (content-addressed): pruned file by file, never as a whole.
    stale_file_units: list[Path] = []
    # Directories whose children are CI job scratch (logs, build contexts, archives).
    ci_scratch_roots: list[Path] = []
    ci_scratch_days: float = 14.0
    # Never touched, whatever their age (matched against the full path).
    protected_globs: list[str] = [
        "*/journey-rollback*",
        "*/jt-dumps*",
        "*/ledger.jsonl*",
        "*/pterodactyl",
        "*/pterodactyl/*",
        "*/olympus*",
        "*/queue-archives*",
    ]

    @model_validator(mode="after")
    def _deletion_roots_are_safe(self) -> Settings:
        """Every root the policy deletes under is absolute, normalized and outside the forbidden trees."""
        for root in self.deletion_roots():
            text = root.as_posix()
            if not text.startswith("/") or posixpath.normpath(text) != text or text == "/":
                raise UnsafeRootError(f"retention root {text!r} must be an absolute, normalized path other than /")
            if text.startswith("/dev/") and not is_within(text, "/dev/shm"):
                raise UnsafeRootError(f"retention root {text!r} lies under /dev outside /dev/shm")
            for forbidden in FORBIDDEN_ROOTS:
                if is_within(text, forbidden):
                    raise UnsafeRootError(f"retention root {text!r} lies under the forbidden tree {forbidden}")
        return self

    def deletion_roots(self) -> list[Path]:
        """Directories whose children may be removed, plus the cache units that may be pruned themselves."""
        return [
            self.home,
            self.ci_root,
            self.ci_root / "jra",
            self.tmp_root,
            self.shm_jobs_root,
            *self.cache_roots,
            *self.ci_scratch_roots,
            *self.cache_units,
            *self.stale_file_units,
        ]

    def is_allowed_target(self, path: str) -> bool:
        """True when `path` is a cache unit or lies strictly below one of the deletion roots."""
        units = {u.as_posix() for u in (*self.cache_units, *self.stale_file_units)}
        if path in units:
            return True
        parents = (self.home, self.ci_root, self.ci_root / "jra", self.tmp_root, self.shm_jobs_root)
        roots = [r.as_posix() for r in (*parents, *self.cache_roots, *self.ci_scratch_roots)]
        return any(is_within(path, r) and path != r for r in roots)

    @property
    def floor_bytes(self) -> int:
        return int(self.root_free_floor_gib * GIB)

    @property
    def budget_bytes(self) -> int:
        return int(self.cache_budget_gib * GIB)
