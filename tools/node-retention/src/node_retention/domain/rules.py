"""Pure helpers of the retention rules."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from fnmatch import fnmatch

IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
PID_DIR = re.compile(r"^\d{8}T\d{6}Z-(?P<pid>\d+)$")
PYTEST_RUN_DIR = re.compile(r"^run-(?P<pid>\d+)-[A-Za-z0-9_]+$")


def matches_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch(path, g) for g in globs)


def name_matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch(name, g) for g in globs)


def job_pid(dir_name: str) -> int | None:
    """PID encoded in an agent-job directory name (`<UTC stamp>-<pid>`), if any."""
    match = PID_DIR.match(dir_name)
    return int(match.group("pid")) if match else None


def pytest_run_pid(dir_name: str) -> int | None:
    """PID encoded in a pytest owned-scratch directory name (`run-<pid>-<random>`), if any."""
    match = PYTEST_RUN_DIR.match(dir_name)
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
# `LANES_WHO` defaults that name no lane: every job without a lane id shared them, so one waiting job kept every
# other job's trees. They are not owners.
PLACEHOLDER_LANES = frozenset({"unspecified", ""})
# A PR number in a directory name or a ledger `what` text (`pr201-3c9b623`, `PR #201`, `pr-201`).
PR_NUMBER = re.compile(r"(?i)(?<![a-z0-9])pr[-_ #]{0,2}(\d{1,6})(?!\d)")


def pr_numbers(text: str) -> set[int]:
    """PR numbers that a name or a ledger text refers to."""
    return {int(m.group(1)) for m in PR_NUMBER.finditer(text)}


def parse_job_record(text: str) -> tuple[str | None, int | None]:
    """(who, creating pid) of a gate `.agent-job` record: `who=<lane> id=<id> created=<ts>` then `<pid> <start>`."""
    lines = text.splitlines()
    who = None
    if lines:
        match = re.search(r"(?:^|\s)who=(\S+)", lines[0])
        who = match.group(1) if match else None
    pid = None
    if len(lines) > 1:
        first = lines[1].split()
        if first and first[0].isdigit():
            pid = int(first[0])
    return who, pid


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


def job_lanes(rows: list[dict[str, object]], is_alive: Callable[[int], bool]) -> tuple[set[str], set[str]]:
    """Return (every lane named by the ledger, lanes with a job running).

    A lane is active when the last row of one of its job ids is neither `end`, `refused` nor `deferred` and
    the row's pid is alive (or absent). A job waiting for admission holds no tree yet, so it does not keep the
    lane's idle trees: on 2026-11-25 deferred jobs of the shared lane `unspecified` kept 1.6 GB of ended trees
    in RAM while swap was full (docs/adr/node_disk_retention_adr.md, "Root floor on its own device").
    Placeholder lanes (`unspecified`) name no owner and are never returned as known lanes.
    """
    last: dict[str, dict[str, object]] = {}
    known: set[str] = set()
    for row in rows:
        who = row.get("who")
        if isinstance(who, str) and who and who not in PLACEHOLDER_LANES:
            known.add(who)
        job_id = row.get("id")
        # A note row (tree gc, reports) says nothing about whether the job still runs.
        if isinstance(job_id, str) and job_id and isinstance(who, str) and who and row.get("event") != "note":
            last[job_id] = row
    active: set[str] = set()
    for row in last.values():
        if row.get("event") in _FINISHED_EVENTS or row.get("event") == "deferred":
            continue
        pid = row.get("pid")
        if isinstance(pid, int) and not is_alive(pid):
            continue
        if str(row["who"]) in PLACEHOLDER_LANES:
            continue
        active.add(str(row["who"]))
    return known, active


def lane_of(tree_name: str, known: set[str]) -> str | None:
    """Lane that owns a tree named `<lane>-<rest>`: the longest known lane name that prefixes it."""
    best = None
    for lane in known:
        if tree_name.startswith(lane + "-") and (best is None or len(lane) > len(best)):
            best = lane
    return best
