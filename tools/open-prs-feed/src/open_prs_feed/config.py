"""Typed runtime settings (`OPEN_PRS_FEED_*`, optionally from an env file)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from open_prs_feed.domain.models import OWNER_RE, REPO_RE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPEN_PRS_FEED_", extra="ignore")

    # At least one of these: owners whose every repository is covered (one GraphQL query each), and single
    # owner/name repositories outside those owners. Cover every repository that has PR-tied job dirs on the node.
    owners: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    # Directory that receives the files: local path, or an absolute POSIX path on `ssh_host`.
    output_dir: str = Field(min_length=1)
    # When set, files are written on this host through OpenSSH (`ssh_command`) instead of locally.
    ssh_host: str | None = None
    numbers_file: str = "open-prs.json"
    detail_file: str = "open-prs.detail.json"
    gh_command: list[str] = Field(default_factory=lambda: ["gh"], min_length=1)
    ssh_command: list[str] = Field(default_factory=lambda: ["ssh"], min_length=1)
    limit: int = Field(default=500, ge=2)
    gh_timeout_s: float = Field(default=60.0, gt=0)
    ssh_timeout_s: float = Field(default=60.0, gt=0)
    allow_empty: bool = False

    @field_validator("repos")
    @classmethod
    def _repos(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if not REPO_RE.match(r)]
        if bad:
            raise ValueError(f"repositories must be owner/name: {bad}")
        if len(set(v)) != len(v):
            raise ValueError("repositories repeat")
        return v

    @field_validator("owners")
    @classmethod
    def _owners(cls, v: list[str]) -> list[str]:
        bad = [o for o in v if not OWNER_RE.match(o)]
        if bad:
            raise ValueError(f"owners must be GitHub logins: {bad}")
        if len(set(v)) != len(v):
            raise ValueError("owners repeat")
        return v

    @field_validator("numbers_file", "detail_file")
    @classmethod
    def _plain_name(cls, v: str) -> str:
        if not v or "/" in v or "\\" in v or v.startswith("."):
            raise ValueError(f"file name must be a plain name without directories: {v!r}")
        return v

    @model_validator(mode="after")
    def _paths(self) -> Settings:
        if not self.owners and not self.repos:
            raise ValueError("set OPEN_PRS_FEED_OWNERS or OPEN_PRS_FEED_REPOS (or both)")
        if self.numbers_file == self.detail_file:
            raise ValueError("numbers_file and detail_file must differ")
        if self.ssh_host is not None and not PurePosixPath(self.output_dir).is_absolute():
            raise ValueError("output_dir must be an absolute POSIX path when ssh_host is set")
        return self

    def local_dir(self) -> Path:
        return Path(self.output_dir)

    def remote_dir(self) -> PurePosixPath:
        return PurePosixPath(self.output_dir)
