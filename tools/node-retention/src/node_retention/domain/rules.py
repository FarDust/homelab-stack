"""Pure helpers of the retention rules."""

from __future__ import annotations

import re
from fnmatch import fnmatch

PID_DIR = re.compile(r"^\d{8}T\d{6}Z-(?P<pid>\d+)$")


def matches_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch(path, g) for g in globs)


def name_matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch(name, g) for g in globs)


def job_pid(dir_name: str) -> int | None:
    """PID encoded in an agent-job directory name (`<UTC stamp>-<pid>`), if any."""
    match = PID_DIR.match(dir_name)
    return int(match.group("pid")) if match else None


def is_within(path: str, other: str) -> bool:
    """True when `path` equals `other` or lies below it."""
    return path == other or path.startswith(other.rstrip("/") + "/")


def in_use(path: str, held: set[str]) -> bool:
    """True when any held path (open file, cwd, container bind source) is `path` or lies inside it.

    A held path that merely contains `path` (a worker's cwd at the parent directory, a monitoring
    container that bind-mounts `/` or `/tmp`) does not show that `path` itself is in use.
    """
    return any(is_within(h, path) for h in held)
