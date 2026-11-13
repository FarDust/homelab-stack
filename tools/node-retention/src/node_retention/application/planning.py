"""Build the prune plan from the policy thresholds. Read-only: nothing is deleted here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from node_retention.config import Settings
from node_retention.domain.models import Candidate, Category, Plan, Skipped
from node_retention.domain.ports import Clock, Docker, FileSystem, Processes
from node_retention.domain.rules import in_use, job_pid, matches_any, name_matches_any

HOUR = 3600.0
DAY = 86400.0


@dataclass(frozen=True)
class Ports:
    fs: FileSystem
    procs: Processes
    docker: Docker
    clock: Clock


class Planner:
    def __init__(self, settings: Settings, ports: Ports) -> None:
        self._s = settings
        self._p = ports
        self._open: set[str] = set()
        self._mounts: set[str] = set()
        self._now = 0.0
        self.candidates: list[Candidate] = []
        self.skipped: list[Skipped] = []

    def build(self) -> Plan:
        s, p = self._s, self._p
        self._now = p.clock.now()
        self._open = p.procs.open_paths()
        self._mounts = p.docker.mount_sources()
        self.candidates, self.skipped = [], []

        self._evidence()
        self._tarballs()
        self._tmp()
        self._shm()
        self._ci_scratch()
        free = p.fs.free_bytes(s.root_mount.as_posix())
        # tmpfs and Docker's own filesystem do not count toward the root floor.
        freed_on_root = sum(
            c.size_bytes
            for c in self.candidates
            if c.action == "remove_path" and not c.path.startswith(s.shm_jobs_root.as_posix())
        )
        budget_used = self._tool_caches(free, freed_on_root)
        self._docker()
        return Plan(
            host=s.host,
            generated_at=self._now,
            root_free_bytes=free,
            root_floor_bytes=s.floor_bytes,
            budget_bytes=s.budget_bytes,
            budget_used_bytes=budget_used,
            floor_violated=free < s.floor_bytes,
            candidates=self.candidates,
            skipped=self.skipped,
        )

    # -- selection helpers -------------------------------------------------------------

    def _gate(
        self, path: str, category: Category, min_age_s: float, reason: str, idle_s: float | None = None
    ) -> Candidate | None:
        """Return a candidate when `path` is old enough, idle, unprotected and not in use.

        `min_age_s` applies to the newest write; `idle_s` (default: the policy's idle window) to the newest
        read or write. The reason a path is kept is recorded in `skipped`.
        """
        p, s = self._p, self._s
        if not p.fs.exists(path):
            return None
        idle_gate = s.idle_hours * HOUR if idle_s is None else idle_s
        st = p.fs.stats(path)
        age = max(0.0, self._now - st.newest_mtime)
        idle = max(0.0, self._now - st.newest_ts)
        if matches_any(path, s.protected_globs):
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason="protected path"))
            return None
        if age < min_age_s:
            reason_text = f"written {age / HOUR:.1f} h ago, gate {min_age_s / HOUR:.0f} h"
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=reason_text))
            return None
        if idle < idle_gate:
            reason_text = f"used {idle / HOUR:.1f} h ago, gate {idle_gate / HOUR:.0f} h"
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=reason_text))
            return None
        if in_use(path, self._open):
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason="open by a process"))
            return None
        if in_use(path, self._mounts):
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason="mounted into a container"))
            return None
        return Candidate(
            category=category,
            action="remove_path",
            path=path,
            size_bytes=st.size_bytes,
            age_seconds=age,
            min_idle_seconds=idle_gate,
            reason=reason,
        )

    def _add(self, cand: Candidate | None) -> None:
        if cand is not None:
            self.candidates.append(cand)

    # -- rules ---------------------------------------------------------------------------

    def _evidence(self) -> None:
        s = self._s
        gate = s.evidence_days * DAY
        reason = f"CI evidence untouched for {s.evidence_days:g} days"
        for path in self._p.fs.children(s.ci_root.as_posix()):
            if name_matches_any(PurePosixPath(path).name, s.evidence_globs):
                self._add(self._gate(path, Category.EVIDENCE, gate, reason))
        for path in self._p.fs.children((s.ci_root / "jra").as_posix()):
            if "evidence" in PurePosixPath(path).name:
                self._add(self._gate(path, Category.EVIDENCE, gate, reason))

    def _tarballs(self) -> None:
        s = self._s
        reason = f"CI git-archive tarball older than {s.tarball_days:g} days"
        for path in self._p.fs.children(s.home.as_posix()):
            if name_matches_any(PurePosixPath(path).name, s.tarball_globs):
                self._add(self._gate(path, Category.TARBALL, s.tarball_days * DAY, reason))

    def _ci_scratch(self) -> None:
        s = self._s
        reason = f"CI scratch untouched for {s.ci_scratch_days:g} days"
        for root in s.ci_scratch_roots:
            for path in self._p.fs.children(root.as_posix()):
                self._add(self._gate(path, Category.CI_SCRATCH, s.ci_scratch_days * DAY, reason))

    def _tmp(self) -> None:
        s = self._s
        reason = f"job leftover idle for {s.tmp_idle_days:g} days"
        for path in self._p.fs.children(s.tmp_root.as_posix()):
            if self._p.fs.owned_by_current_user(path):
                self._add(self._gate(path, Category.TMP, s.tmp_idle_days * DAY, reason))

    def _shm(self) -> None:
        s = self._s
        for path in self._p.fs.children(s.shm_jobs_root.as_posix()):
            pid = job_pid(PurePosixPath(path).name)
            if pid is None:
                reason = f"job dir idle for {s.shm_idle_hours:g} h"
                self._add(self._gate(path, Category.SHM, s.shm_idle_hours * HOUR, reason))
            elif self._p.procs.is_alive(pid):
                size = self._p.fs.stats(path).size_bytes
                self.skipped.append(Skipped(path=path, size_bytes=size, reason=f"job pid {pid} is alive"))
            else:
                self._add(self._gate(path, Category.SHM, 0.0, f"job pid {pid} is dead", s.shm_dead_idle_hours * HOUR))

    def _tool_caches(self, free: int, freed_on_root: int) -> int:
        """Prune the least recently used tool caches only when the budget or the floor needs it."""
        s, p = self._s, self._p
        stale_units = [u.as_posix() for u in s.stale_file_units]
        units = [u.as_posix() for u in s.cache_units]
        for root in s.cache_roots:
            units.extend(p.fs.children(root.as_posix()))
        units = [u for u in dict.fromkeys(units) if u not in stale_units]
        sized = [(u, p.fs.stats(u)) for u in units if p.fs.exists(u)]
        stale_sized = [(u, p.fs.stats(u)) for u in stale_units if p.fs.exists(u)]
        used = sum(st.size_bytes for _, st in sized + stale_sized)
        need = max(used - s.budget_bytes, s.floor_bytes - (free + freed_on_root), 0)
        if need == 0:
            return used
        gained = 0
        cutoff = self._now - s.idle_hours * HOUR
        for path, _ in sorted(stale_sized, key=lambda item: item[1].newest_ts):
            if gained >= need:
                break
            if matches_any(path, s.protected_globs) or in_use(path, self._mounts):
                continue
            found = p.fs.stale_files(path, cutoff)
            if found.size_bytes > 0:
                self.candidates.append(
                    Candidate(
                        category=Category.STALE_CACHE_FILES,
                        action="prune_stale_files",
                        path=path,
                        size_bytes=found.size_bytes,
                        age_seconds=0,
                        min_idle_seconds=s.idle_hours * HOUR,
                        reason=f"{found.count} cache files not read or written for {s.idle_hours:g} h",
                    )
                )
                gained += found.size_bytes
        for path, _ in sorted(sized, key=lambda item: item[1].newest_ts):
            if gained >= need:
                break
            cand = self._gate(
                path, Category.TOOL_CACHE, s.idle_hours * HOUR, "least recently used tool cache over budget or floor"
            )
            if cand is not None:
                self.candidates.append(cand)
                gained += cand.size_bytes
        return used

    def _docker(self) -> None:
        d, days = self._p.docker, self._s.docker_build_cache_days
        dangling = d.dangling_images_reclaimable()
        if dangling > 0:
            self.candidates.append(
                Candidate(
                    category=Category.DOCKER_IMAGES,
                    action="docker_image_prune",
                    path="docker:dangling-images",
                    size_bytes=dangling,
                    age_seconds=0,
                    reason="dangling images, not referenced by any container (size is an upper bound; layers may be shared)",
                )
            )
        cache = d.build_cache_reclaimable()
        if cache > 0:
            self.candidates.append(
                Candidate(
                    category=Category.DOCKER_BUILD_CACHE,
                    action="docker_builder_prune",
                    path="docker:build-cache",
                    size_bytes=cache,
                    age_seconds=days * DAY,
                    reason=f"build cache unused for {days} days (size is an upper bound)",
                )
            )
