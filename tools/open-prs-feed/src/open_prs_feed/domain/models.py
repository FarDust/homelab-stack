"""Snapshot of open pull requests and the two file formats rendered from it."""

from __future__ import annotations

import json
import re

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PositiveInt, field_validator

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SCHEMA_VERSION = 1


class OpenPr(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo: str
    number: PositiveInt
    head_sha8: str = Field(pattern=r"^[0-9a-f]{8}$")
    branch: str = Field(min_length=1)
    updated_at: AwareDatetime

    @field_validator("repo")
    @classmethod
    def _repo(cls, v: str) -> str:
        if not REPO_RE.match(v):
            raise ValueError(f"repository must be owner/name, got {v!r}")
        return v


class Snapshot(BaseModel):
    """A complete answer for every configured repository."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = SCHEMA_VERSION
    generated_at: AwareDatetime
    repos: tuple[str, ...]
    prs: tuple[OpenPr, ...]

    def numbers(self) -> list[int]:
        """PR numbers across repositories. A number shared by two repositories counts once (protects both)."""
        return sorted({pr.number for pr in self.prs})

    def render_numbers(self) -> bytes:
        """The consumer contract of node-retention `OpenPrsFile`: a JSON array of positive ints."""
        return (json.dumps(self.numbers()) + "\n").encode("utf-8")

    def render_detail(self) -> bytes:
        return (self.model_dump_json(indent=2) + "\n").encode("utf-8")
