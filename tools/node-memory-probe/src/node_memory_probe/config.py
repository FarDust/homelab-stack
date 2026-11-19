"""Typed settings. Environment prefix NODE_MEMORY_PROBE_; list and map settings are JSON."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GIB = 1024**3
MIB = 1024**2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NODE_MEMORY_PROBE_", extra="forbid")

    host: str = Field(min_length=1)
    proc_root: Path = Path("/proc")
    cgroup_root: Path = Path("/sys/fs/cgroup")
    textfile_dir: Path = Path("/var/lib/node_exporter/textfile_collector")
    textfile_name: str = "node_memory_probe.prom"
    state_path: Path = Path("/var/lib/node-memory-probe/state.json")
    snapshot_dir: Path = Path("/var/lib/node-memory-probe/snapshots")

    # Container names whose largest JVM is always probed and may be asked through jcmd (read-only commands).
    jvm_containers: list[str] = Field(default_factory=list)
    # Container (or swarm service) name -> the `process` label to publish, e.g. a short name for a UUID.
    aliases: dict[str, str] = Field(default_factory=dict)
    top_swap_processes: int = Field(default=5, ge=0, le=20)
    top_mappings: int = Field(default=30, ge=1, le=200)
    top_cgroups: int = Field(default=10, ge=0, le=50)
    top_readers: int = Field(default=5, ge=0, le=20)

    # Per-mapping reads and jcmd are skipped while the host's CPU is this contended (PSI some avg10, percent).
    cpu_psi_skip_avg10: float = Field(default=60.0, gt=0, le=100)

    snapshot_swap_free_below_bytes: int = Field(default=3 * GIB, ge=0)
    snapshot_pswpout_pages_per_second: float = Field(default=100.0, ge=0)
    snapshot_swap_free_min_interval_seconds: float = Field(default=900.0, ge=0)
    snapshot_retention_days: float = Field(default=14.0, gt=0)
    snapshot_budget_bytes: int = Field(default=200 * MIB, gt=0)

    # jcmd attaches to the target JVM (SIGQUIT to its signal dispatcher, a short-lived second JVM in its container):
    # the one deliberate exception to "never signal", see docs/adr/node_memory_probe_adr.md. Set false to forbid it.
    jcmd_enabled: bool = True
    docker_bin: str = "docker"
    docker_timeout_seconds: float = Field(default=15.0, gt=0, le=50)
