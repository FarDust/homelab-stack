"""Pure helpers of the retention rules."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from fnmatch import fnmatch

IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
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


def overlaps(path: str, other: str) -> bool:
    """True when either path lies at or below the other."""
    return is_within(path, other) or is_within(other, path)


def contains_mount(path: str, mount_points: set[str]) -> bool:
    """True when a mount point is `path` or lies below it: removing it would cross into another filesystem."""
    return any(is_within(m, path) for m in mount_points)


# Job-ledger events after which a job no longer runs. Every other last event (start, deferred, note) means
# the job may still be running or about to create its scratch.
_FINISHED_EVENTS = frozenset({"end", "refused"})
_PATH_FIELDS = ("where_fs", "where", "workdir")


def running_job_paths(rows: list[dict[str, object]], is_alive: Callable[[int], bool]) -> set[str]:
    """Absolute paths named by ledger jobs that may still run.

    A job runs when its last row (by `id`) is not an end or refused row and its pid is alive or unknown. A
    reused pid keeps a finished job protected, which errs on the safe side.
    """
    last: dict[str, dict[str, object]] = {}
    for row in rows:
        job_id = row.get("id")  # notes and host rows carry no id: they name no job
        if isinstance(job_id, str) and job_id:
            last[job_id] = row
    held: set[str] = set()
    for row in last.values():
        if row.get("event") in _FINISHED_EVENTS:
            continue
        pid = row.get("pid")
        if isinstance(pid, int) and not is_alive(pid):
            continue
        for field in _PATH_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value.startswith("/"):
                held.add(posixpath.normpath(value))
    return held
