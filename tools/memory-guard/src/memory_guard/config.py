"""Typed runtime settings (`MEMORY_GUARD_*`, optionally from an env file)."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORY_GUARD_", extra="ignore")

    state_dir: Path
    # Argument list separated by `|` (env files need no quote characters); `{message}` is replaced by the alert text.
    # Required: no silent default alert path.
    alert_command: Annotated[list[str], NoDecode] = Field(min_length=1)
    # Text that must appear in the alert command's stdout to count as delivered (agent-bridge prints "delivered <id>").
    alert_confirm: str = "delivered"
    alert_timeout_s: float = Field(default=60.0, gt=0)
    host: str = Field(default_factory=socket.gethostname, min_length=1)
    min_free_virtual_gb: float = Field(default=8.0, gt=0)
    min_free_ram_gb: float = Field(default=1.0, gt=0)
    samples: int = Field(default=2, ge=1)
    alert_interval_min: float = Field(default=30.0, gt=0)
    top_n: int = Field(default=10, ge=1)
    # Opt-in WSL page-cache drop (docs/adr/memory_guard_adr.md, addendum 0.2.0). Kill switch: set to false.
    reclaim_enabled: bool = True
    reclaim_samples: int = Field(default=2, ge=1)
    reclaim_min_interval_min: float = Field(default=10.0, gt=0)
    reclaim_max_per_hour: int = Field(default=6, ge=1)
    reclaim_timeout_s: float = Field(default=60.0, gt=0)
    reclaim_settle_s: float = Field(default=20.0, ge=0)
    # Cause attribution (docs/adr/memory_guard_adr.md, addendum 0.3.0). Base URL of the Ollama API, for `GET /api/ps`.
    # Unset: the alert says "cause unknown: MEMORY_GUARD_OLLAMA_URL is not set" instead of guessing.
    ollama_url: str | None = None
    ollama_timeout_s: float = Field(default=5.0, gt=0)
    # Host GPU dedicated memory at or above this, with no Ollama model resident, is reported as another GPU consumer.
    gpu_other_gb: float = Field(default=4.0, gt=0)
    wsl_distro: str = Field(default="Ubuntu", min_length=1)
    # Commit-headroom textfile for node-exporter in the guest (docs/adr/memory_guard_adr.md, addendum 0.4.0).
    # Feature flag, off by default: `publish-headroom` exits 0 without touching WSL while false.
    headroom_publish_enabled: bool = False
    headroom_host_label: str = Field(default="gabriel-pc", pattern=r"^[A-Za-z0-9_.:-]+$")
    headroom_timeout_s: float = Field(default=30.0, gt=0)

    @field_validator("alert_command", mode="before")
    @classmethod
    def _split_command(cls, value: object) -> object:
        return [part for part in value.split("|") if part] if isinstance(value, str) else value
