"""Typed runtime settings (`MEMORY_GUARD_*`, optionally from an env file)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORY_GUARD_", extra="ignore")

    state_dir: Path
    # JSON list; `{message}` is replaced by the alert text. Required: no silent default alert path.
    alert_command: list[str] = Field(min_length=1)
    # Text that must appear in the alert command's stdout to count as delivered (agent-bridge prints "delivered <id>").
    alert_confirm: str = "delivered"
    alert_timeout_s: float = Field(default=60.0, gt=0)
    host: str = "gabriel-pc"
    min_free_virtual_gb: float = Field(default=8.0, gt=0)
    min_free_ram_gb: float = Field(default=1.0, gt=0)
    samples: int = Field(default=2, ge=1)
    alert_interval_min: float = Field(default=30.0, gt=0)
    top_n: int = Field(default=10, ge=1)
