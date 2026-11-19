"""Retention of the RAM-backed job trees under `/dev/shm/agent-jobs`.

Decision record: docs/adr/node_disk_retention_adr.md, section "Tmpfs job trees". Read-only: it proposes candidates,
and the planner's gate decides whether a path is in use (open file, cwd, container mount, running job of the ledger).

Rules, evaluated per tree and then for the whole directory:

1. a tree named `<UTC stamp>-<pid>` goes one hour after its pid died; while the pid lives it stays;
2. any other tree untouched for `shm_idle_hours` (24 h) goes whatever its lane does;
3. any other tree untouched for `shm_idle_minutes` (120 min) goes when its lane has no job running or deferred;
4. while the directory exceeds `shm_cap_gib`, the oldest trees idle for at least `shm_cap_min_idle_minutes` go first.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from node_retention.config import Settings
from node_retention.domain.models import Candidate, Category, Skipped, TreeStats
from node_retention.domain.rules import in_use, job_lanes, job_pid, lane_of

if TYPE_CHECKING:
    from node_retention.application.planning import Ports

HOUR = 3600.0
MINUTE = 60.0

# gate(path, category, min_age_s, reason, idle_s) -> Candidate | None; records its own skip reason.
Gate = Callable[[str, Category, float, str, float | None], Candidate | None]


class ShmTreePolicy:
    def __init__(
        self,
        settings: Settings,
        ports: Ports,
        gate: Gate,
        skipped: list[Skipped],
        now: float,
        held: set[str],
    ) -> None:
        """`held`: paths open in a process or bind-mounted into a container, read once by the planner."""
        self._s = settings
        self._p = ports
        self._held = held
        self._gate = gate
        self._skipped = skipped
        self._now = now

    def candidates(self) -> list[Candidate]:
        s, p = self._s, self._p
        # Fails closed: an unreadable ledger raises, so no tree is judged without knowing the active lanes.
        known, active = job_lanes(p.jobs.rows(), p.procs.is_alive)
        trees: list[tuple[str, TreeStats]] = []
        for path in p.fs.children(s.shm_jobs_root.as_posix()):
            if p.fs.exists(path):
                trees.append((path, p.fs.stats(path)))
        total = sum(st.size_bytes for _, st in trees)
        chosen: list[Candidate] = []
        self._kept_for_lane = kept_for_lane = set()
        waiting: list[tuple[str, TreeStats]] = []  # not collectable by rules 1-3, still eligible for rule 4
        for path, st in trees:
            cand, evictable = self._judge(path, st, known, active)
            if cand is not None:
                chosen.append(cand)
            elif evictable:
                waiting.append((path, st))
        remaining = total - sum(c.size_bytes for c in chosen)
        if remaining > s.shm_cap_bytes:
            reason = f"{s.shm_jobs_root.as_posix()} holds {total / 1024**3:.1f} GiB, cap {s.shm_cap_gib:g} GiB: oldest idle first"
            for path, _ in sorted(waiting, key=lambda item: (item[0] in kept_for_lane, item[1].newest_ts)):
                if remaining <= s.shm_cap_bytes:
                    break
                cand = self._gate(path, Category.SHM, 0.0, reason, s.shm_cap_min_idle_minutes * MINUTE)
                if cand is not None:
                    chosen.append(cand)
                    remaining -= cand.size_bytes
        return chosen

    def _judge(self, path: str, st: TreeStats, known: set[str], active: set[str]) -> tuple[Candidate | None, bool]:
        """(candidate, evictable by the cap). A tree in use or owned by a live pid is never evictable."""
        s = self._s
        name = PurePosixPath(path).name
        idle = max(0.0, self._now - st.newest_ts)
        pid = job_pid(name)
        if pid is not None:
            if self._p.procs.is_alive(pid):
                self._skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=f"job pid {pid} is alive"))
                return None, False
            return self._gate(path, Category.SHM, 0.0, f"job pid {pid} is dead", s.shm_dead_idle_hours * HOUR), False
        if idle >= s.shm_idle_hours * HOUR:
            reason = f"tree untouched for {idle / HOUR:.1f} h (limit {s.shm_idle_hours:g} h, any lane)"
            return self._gate(path, Category.SHM, 0.0, reason, s.shm_idle_hours * HOUR), False
        lane = lane_of(name, known)
        if lane is None or lane in active:
            # An unknown lane left no ledger row, so nothing says its job is over: it is kept like an active lane.
            self._kept_for_lane.add(path)
            self._skipped.append(
                Skipped(
                    path=path,
                    size_bytes=st.size_bytes,
                    reason=f"lane {lane} has a job running or deferred"
                    if lane
                    else "no ledger lane owns it; kept until the 24 h ceiling",
                )
            )
            return None, self._usable(path)
        if idle >= s.shm_idle_minutes * MINUTE:
            reason = (
                f"tree untouched for {idle / MINUTE:.0f} min (limit {s.shm_idle_minutes:g} min); "
                f"lane {lane} has no job running or deferred"
            )
            return self._gate(path, Category.SHM, 0.0, reason, s.shm_idle_minutes * MINUTE), False
        self._skipped.append(
            Skipped(
                path=path,
                size_bytes=st.size_bytes,
                reason=f"used {idle / MINUTE:.0f} min ago, gate {s.shm_idle_minutes:g} min",
            )
        )
        return None, self._usable(path)

    def _usable(self, path: str) -> bool:
        """True unless a process or container uses the tree (the cap never evicts those)."""
        return not in_use(path, self._held)
