"""Root floor step-down: ledger-ended CI job dirs on `/` with stepped age gates.

Decision record: docs/adr/node_disk_retention_adr.md, section "Root floor on its own device". Read-only: it proposes
candidates and the planner's gate decides whether a path is protected, in use or held by a running ledger job.

While `/` stays under its floor after every normal rule, a direct child directory of a CI job root
(`ci_job_roots`, `ci_scratch_roots`) becomes a candidate at the first step gate (3 days, then 1 day) when

- it lies on the floor's filesystem;
- the job ledger names it (a `where`, `where_fs` or `workdir` at or below it), every job id that names it has
  ended (`end` or `refused`), and the newest of those end rows is older than the step gate;
- its newest write is older than the step gate and it was not read for the policy's idle window;
- it is not tied to an open PR: a PR number in its name or in the `what` of a job naming it is kept while that
  PR is open, and every PR-tied dir is kept while open PRs are unknown.

Dirs the ledger never names (owner unknown) are never candidates here. Oldest dirs go first, and the step stops as
soon as the shortfall is covered.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from node_retention.config import Settings
from node_retention.domain.models import Candidate, Category, Skipped
from node_retention.domain.rules import is_within, pr_numbers

if TYPE_CHECKING:
    from node_retention.application.planning import Ports

DAY = 86400.0
_FINISHED = frozenset({"end", "refused"})
_PATH_FIELDS = ("where_fs", "where", "workdir")

# gate(path, category, min_age_s, reason, idle_s) -> Candidate | None; records its own skip reason.
Gate = Callable[[str, Category, float, str, float | None], Candidate | None]


def _ts(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


class JobDirHistory:
    """What the ledger says about each child dir of the job roots: job ids, their last rows and texts."""

    def __init__(self, rows: list[dict[str, object]], roots: list[str]) -> None:
        self.last: dict[str, dict[str, object]] = {}
        self.ids_of: dict[str, set[str]] = {}
        self.texts_of: dict[str, list[str]] = {}
        for row in rows:
            job_id = row.get("id")
            if not isinstance(job_id, str) or not job_id or row.get("event") == "note":
                continue
            self.last[job_id] = row
            for name in _PATH_FIELDS:
                value = row.get(name)
                if not isinstance(value, str) or not value.startswith("/"):
                    continue
                child = _child_of(posixpath.normpath(value), roots)
                if child is None:
                    continue
                self.ids_of.setdefault(child, set()).add(job_id)
                what = row.get("what")
                if isinstance(what, str):
                    self.texts_of.setdefault(child, []).append(what)

    def ended_at(self, child: str) -> float | None:
        """Newest end time of the jobs naming `child`, or None when one of them has not ended (or none names it)."""
        ids = self.ids_of.get(child)
        if not ids:
            return None
        newest = 0.0
        for job_id in ids:
            row = self.last[job_id]
            if row.get("event") not in _FINISHED:
                return None
            ts = _ts(row.get("ts"))
            if ts is None:
                return None
            newest = max(newest, ts)
        return newest


def _child_of(path: str, roots: list[str]) -> str | None:
    """The direct child of the deepest root that holds `path` (strictly below it), else None."""
    best = None
    for root in roots:
        if path != root and is_within(path, root) and (best is None or len(root) > len(best)):
            best = root
    if best is None:
        return None
    first = path[len(best.rstrip("/")) + 1 :].split("/", 1)[0]
    return f"{best.rstrip('/')}/{first}"


class FloorStepDown:
    def __init__(self, settings: Settings, ports: Ports, gate: Gate, now: float, skipped: list[Skipped]) -> None:
        self._s = settings
        self._skipped = skipped
        self._p = ports
        self._gate = gate
        self._now = now

    def _roots(self) -> list[str]:
        # A scratch root that is a kept store (the evidence store) holds products with their own retention, not
        # job dirs; a job root such as `jra` is a real parent of job dirs.
        keep = self._s.ci_job_keep_names
        scratch = (r for r in self._s.ci_scratch_roots if r.name not in keep)
        return [r.as_posix() for r in (*self._s.ci_job_roots, *scratch)]

    def _reserved(self) -> set[str]:
        """Configured roots and caches: never a job dir, even when a ledger row names a path inside one."""
        s = self._s
        paths = (
            s.home,
            s.ci_root,
            s.ci_root / "jra",
            s.tmp_root,
            s.shm_jobs_root,
            *s.cache_roots,
            *s.cache_units,
            *s.stale_file_units,
            *s.ci_scratch_roots,
            *s.ci_job_roots,
        )
        return {p.as_posix() for p in paths}

    def candidates(self, shortfall: int, already: Callable[[str], bool]) -> tuple[list[Candidate], float | None]:
        """Candidates that cover `shortfall` bytes on `/`, and the smallest step gate used (None if none)."""
        s, p = self._s, self._p
        roots = self._roots()
        if not roots or shortfall <= 0:
            return [], None
        history = JobDirHistory(p.jobs.rows(), roots)
        open_prs = p.prs.numbers()
        reserved = self._reserved()
        root_dev = p.fs.device(s.root_mount.as_posix())
        base_days = min(s.ci_scratch_days, s.evidence_days)
        chosen: list[Candidate] = []
        gained = 0
        used_step: float | None = None
        for days in sorted((d for d in s.floor_step_days if d < base_days), reverse=True):
            gate_s = days * DAY
            pool: list[tuple[float, str]] = []
            for child in history.ids_of:
                if child in reserved or PurePosixPath(child).name in s.ci_job_keep_names:
                    continue
                if already(child) or any(c.path == child for c in chosen):
                    continue
                if not p.fs.exists(child) or p.fs.device(child) != root_dev:
                    continue
                ended = history.ended_at(child)
                if ended is None or self._now - ended < gate_s:
                    continue
                if self._pr_tied(child, history, open_prs):
                    why = "tied to an open PR" if open_prs is not None else "tied to a PR and open PRs are unknown"
                    self._skipped.append(Skipped(path=child, size_bytes=0, reason=f"root floor step-down: {why}"))
                    continue
                pool.append((p.fs.stats(child).newest_ts, child))
            for _, child in sorted(pool):
                if gained >= shortfall:
                    break
                reason = (
                    f"root floor step-down: ledger jobs ended {days:g}+ days ago, untouched {days:g} days, "
                    f"no open PR; {shortfall / 1024**3:.2f} GiB short on {s.root_mount.as_posix()}"
                )
                cand = self._gate(child, Category.CI_JOB, gate_s, reason, max(gate_s, s.idle_hours * 3600.0))
                if cand is not None:
                    chosen.append(cand)
                    gained += cand.size_bytes
                    used_step = days
            if gained >= shortfall:
                break
        return chosen, used_step

    @staticmethod
    def _pr_tied(child: str, history: JobDirHistory, open_prs: set[int] | None) -> bool:
        numbers = pr_numbers(PurePosixPath(child).name)
        for text in history.texts_of.get(child, []):
            numbers |= pr_numbers(text)
        if not numbers:
            return False
        if open_prs is None:
            return True  # unknown: keep every PR-tied dir
        return bool(numbers & open_prs)
