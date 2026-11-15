"""Typed report configuration; all paths and deadline evidence are required."""

from __future__ import annotations

import math
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ReportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NODE_RETENTION_REPORT_", extra="forbid", allow_inf_nan=False)

    job_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}Z-[1-9][0-9]*$")
    owner: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    host: str = Field(min_length=1, max_length=255)
    pid: int = Field(gt=0)
    jobs_root: Path
    ledger: Path
    publisher: Path
    parent_death_guard: str = Field(default="/usr/bin/setpriv", pattern=r"^/[^\x00]+$")
    started_epoch: int = Field(gt=0)
    expected_seconds: int = Field(gt=0)
    phase_deadline_epoch: float | None = Field(default=None, gt=0)
    maximum_seconds: float = Field(default=4, gt=0, le=4)
    stale_hours: float = Field(default=6, gt=0)

    @field_validator("jobs_root", "ledger", "publisher")
    @classmethod
    def absolute_paths(cls, path: Path) -> Path:
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("report path must be absolute and normalized")
        return path

    @model_validator(mode="after")
    def owner_identity(self) -> ReportSettings:
        try:
            if not math.isfinite(float(self.original_deadline_epoch)):
                raise ValueError("original deadline must be finite")
        except OverflowError as error:
            raise ValueError("original deadline is outside supported clock range") from error
        if self.job_id.rsplit("-", 1)[1] != str(self.pid):
            raise ValueError("report PID must match the existing job identity")
        if self.phase_deadline_epoch is not None and self.phase_deadline_epoch > self.original_deadline_epoch:
            raise ValueError("report phase deadline cannot extend original job budget")
        return self

    @property
    def original_deadline_epoch(self) -> float:
        return self.started_epoch + self.expected_seconds

    @property
    def deadline_epoch(self) -> float:
        return self.original_deadline_epoch if self.phase_deadline_epoch is None else self.phase_deadline_epoch

    @property
    def stale_seconds(self) -> float:
        return self.stale_hours * 3600
