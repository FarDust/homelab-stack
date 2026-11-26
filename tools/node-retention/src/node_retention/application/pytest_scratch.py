"""Retention of pytest owned-scratch volumes (`HEADLESS_PYTEST_SCRATCH_ROOT`, for example an LV mounted at `/ps`).

Decision record: docs/adr/node_disk_retention_adr.md, section "Pytest scratch volumes". Read-only: it proposes
candidates, and the planner's gate decides whether a path is in use (open file, cwd, container mount, running job
of the ledger), protected, or too recent.

The pytest plugin names each run `run-<pid>-<random>` and removes it when the session ends cleanly; a failed run keeps
its directory on purpose (`retention=failed`), and a killed or out-of-space run never reaches its cleanup. Rules:

1. `run-<pid>-<random>` whose pid is dead goes `pytest_scratch_dead_hours` (2 h) after its last use;
2. while the root holds more than `pytest_scratch_cap_gib`, dead ones go oldest first once idle for
   `pytest_scratch_cap_min_idle_minutes`;
3. a live pid keeps its directory, and any other name is never a candidate (its owner is unknown).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from node_retention.config import Settings
from node_retention.domain.models import Candidate, Category, Skipped, TreeStats
from node_retention.domain.rules import pytest_run_pid

if TYPE_CHECKING:
    from node_retention.application.planning import Ports

HOUR = 3600.0
MINUTE = 60.0

# gate(path, category, min_age_s, reason, idle_s) -> Candidate | None; records its own skip reason.
Gate = Callable[[str, Category, float, str, float | None], Candidate | None]


class PytestScratchPolicy:
    def __init__(self, settings: Settings, ports: Ports, gate: Gate, skipped: list[Skipped]) -> None:
        self._s = settings
        self._p = ports
        self._gate = gate
        self._skipped = skipped

    def candidates(self) -> list[Candidate]:
        chosen: list[Candidate] = []
        for root in self._s.pytest_scratch_roots:
            chosen.extend(self._root(root.as_posix()))
        return chosen

    def _root(self, root: str) -> list[Candidate]:
        s, p = self._s, self._p
        chosen: list[Candidate] = []
        waiting: list[tuple[str, TreeStats, int]] = []  # dead but too recent for rule 1, eligible for rule 2
        total = 0
        for path in p.fs.children(root):
            if not p.fs.exists(path):
                continue
            st = p.fs.stats(path)
            total += st.size_bytes
            pid = pytest_run_pid(PurePosixPath(path).name)
            if pid is None:
                self._skipped.append(
                    Skipped(path=path, size_bytes=st.size_bytes, reason="not a pytest run directory; owner unknown")
                )
                continue
            if p.procs.is_alive(pid):
                self._skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=f"pytest pid {pid} is alive"))
                continue
            cand = self._gate(
                path, Category.PYTEST_SCRATCH, 0.0, f"pytest pid {pid} is dead", s.pytest_scratch_dead_hours * HOUR
            )
            if cand is not None:
                chosen.append(cand)
            else:
                waiting.append((path, st, pid))
        remaining = total - sum(c.size_bytes for c in chosen)
        cap = int(s.pytest_scratch_cap_gib * 1024**3)
        if remaining > cap:
            reason = (
                f"{root} holds {total / 1024**3:.1f} GiB, cap {s.pytest_scratch_cap_gib:g} GiB: oldest dead run first"
            )
            for path, _, pid in sorted(waiting, key=lambda item: item[1].newest_ts):
                if remaining <= cap:
                    break
                cand = self._gate(
                    path,
                    Category.PYTEST_SCRATCH,
                    0.0,
                    f"{reason}; pytest pid {pid} is dead",
                    s.pytest_scratch_cap_min_idle_minutes * MINUTE,
                )
                if cand is not None:
                    chosen.append(cand)
                    remaining -= cand.size_bytes
        return chosen
