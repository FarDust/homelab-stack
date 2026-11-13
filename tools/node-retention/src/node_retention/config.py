"""Typed thresholds and paths. Environment prefix NODE_RETENTION_, nested delimiter `__`."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GIB = 1024**3


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
        "*/pterodactyl/*",
        "*/olympus*",
        "*/queue-archives*",
    ]

    @property
    def floor_bytes(self) -> int:
        return int(self.root_free_floor_gib * GIB)

    @property
    def budget_bytes(self) -> int:
        return int(self.cache_budget_gib * GIB)
