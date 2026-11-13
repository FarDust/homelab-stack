"""Domain rules of break-glass flag control: valid keys, environments and outcomes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

FLAG_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class BreakGlassError(Exception):
    """A break-glass operation failed; the message names the operation, the flag and the recovery."""


class Path(StrEnum):
    """Which control path changed the flag."""

    ADMIN_API = "admin-api"
    DATABASE = "database"


@dataclass(frozen=True)
class FlagTarget:
    key: str
    project: str
    environment: str

    def __post_init__(self) -> None:
        if not FLAG_KEY.fullmatch(self.key):
            raise BreakGlassError(f"flag key {self.key!r} is not a dotted lowercase key such as trail.recording")
        if not self.project or not self.environment:
            raise BreakGlassError("project and environment are required")


@dataclass(frozen=True)
class SwitchOutcome:
    target: FlagTarget
    enabled: bool
    path: Path
    verified: bool
    note: str
