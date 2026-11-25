"""Build the prune plan from the policy thresholds. Read-only: nothing is deleted here."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from node_retention.application.floor_step_down import FloorStepDown
from node_retention.application.safety import protected_image_violations, running_jobs, unsafe_reason
from node_retention.application.shm_trees import ShmTreePolicy
from node_retention.config import Settings
from node_retention.domain.models import Candidate, Category, Plan, Skipped
from node_retention.domain.ports import Clock, Docker, FileSystem, JobLedger, OpenPullRequests, Processes
from node_retention.domain.rules import in_use, is_within, matches_any, name_matches_any

HOUR = 3600.0
DAY = 86400.0


class UnknownPullRequests:
    """Default answer when nothing reports open PRs: unknown, so every PR-tied dir is kept by the step-down."""

    def numbers(self) -> set[int] | None:
        return None


@dataclass(frozen=True)
class Ports:
    fs: FileSystem
    procs: Processes
    docker: Docker
    clock: Clock
    jobs: JobLedger
    prs: OpenPullRequests = field(default_factory=UnknownPullRequests)


class Planner:
    def __init__(self, settings: Settings, ports: Ports) -> None:
        self._s = settings
        self._p = ports
        self._open: set[str] = set()
        self._mounts: set[str] = set()
        self._mount_points: set[str] = set()
        self._jobs: set[str] = set()
        self._image_violations: list[str] = []
        self._now = 0.0
        self._root_dev_id: int | None = None
        self._docker_root_on_root: bool | None = None
        self.candidates: list[Candidate] = []
        self.skipped: list[Skipped] = []

    def build_shm(self) -> Plan:
        """Plan only the tmpfs job trees (the `shm-gc` command: gate end hook and the 10-minute guard)."""
        self._prepare()
        self._shm()
        return self._plan(free=self._p.fs.free_bytes(self._s.root_mount.as_posix()), budget_used=0)

    def _prepare(self) -> None:
        p = self._p
        self._now = p.clock.now()
        self._open = p.procs.open_paths()
        self._mounts = p.docker.mount_sources()
        self._mount_points = p.fs.mount_points()
        # Fails closed: an unreadable ledger raises here, before any candidate exists.
        self._jobs = running_jobs(self._s, p.jobs, p.procs)
        self.candidates, self.skipped = [], []

    def build(self) -> Plan:
        s, p = self._s, self._p
        self._prepare()
        self._evidence()
        self._tarballs()
        self._tmp()
        self._shm()
        self._ci_scratch()
        free = p.fs.free_bytes(s.root_mount.as_posix())
        # Only bytes on the floor's own filesystem count toward it: tmpfs, a separate `/tmp` volume and Docker's
        # data root free nothing on `/` (docs/adr/node_disk_retention_adr.md, "Root floor on its own device").
        budget_used = self._tool_caches(free, self._root_bytes())
        self._docker()
        step_days: float | None = None
        if free + self._root_bytes() < s.floor_bytes:
            step = FloorStepDown(s, p, self._gate, self._now, self.skipped)
            chosen, step_days = step.candidates(s.floor_bytes - free - self._root_bytes(), self._is_candidate)
            self.candidates.extend(chosen)
        return self._plan(free=free, budget_used=budget_used, step_days=step_days)

    def _plan(self, free: int, budget_used: int, step_days: float | None = None) -> Plan:
        s = self._s
        reclaimable = self._root_bytes()
        unmet = ""
        if free + reclaimable < s.floor_bytes:
            unmet = (
                f"candidates free {reclaimable / 1024**3:.2f} GiB on {s.root_mount.as_posix()}, "
                f"{(s.floor_bytes - free - reclaimable) / 1024**3:.2f} GiB short of the floor after every rule "
                "and the step-down; what is left is kept (see skipped)"
            )
        # A path judged by several rules keeps its last reason; a candidate is not also listed as skipped.
        chosen = {c.path for c in self.candidates}
        skipped = list({sk.path: sk for sk in self.skipped if sk.path not in chosen}.values())
        return Plan(
            host=s.host,
            generated_at=self._now,
            root_free_bytes=free,
            root_floor_bytes=s.floor_bytes,
            budget_bytes=s.budget_bytes,
            budget_used_bytes=budget_used,
            floor_violated=free < s.floor_bytes,
            root_reclaimable_bytes=reclaimable,
            floor_step_days=step_days,
            floor_unmet_reason=unmet,
            candidates=self.candidates,
            skipped=skipped,
            protected_image_violations=self._image_violations,
        )

    # -- floor accounting ------------------------------------------------------------

    def _is_candidate(self, path: str) -> bool:
        return any(c.path == path for c in self.candidates)

    def _on_root(self, cand: Candidate) -> bool:
        """True when deleting `cand` frees space on the floor's filesystem (same `st_dev` as `root_mount`)."""
        if cand.action in ("docker_image_prune", "docker_builder_prune"):
            return self._docker_on_root()
        return self._path_on_root(cand.path)

    def _path_on_root(self, path: str) -> bool:
        try:
            return self._p.fs.device(path) == self._root_dev()
        except FileNotFoundError:
            return False

    def _root_dev(self) -> int:
        if self._root_dev_id is None:
            self._root_dev_id = self._p.fs.device(self._s.root_mount.as_posix())
        return self._root_dev_id

    def _docker_on_root(self) -> bool:
        if self._docker_root_on_root is None:
            self._docker_root_on_root = self._path_on_root(self._p.docker.data_root())
        return self._docker_root_on_root

    def _root_bytes(self) -> int:
        return sum(c.size_bytes for c in self.candidates if self._on_root(c))

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
        unsafe = unsafe_reason(s, p.fs, path, self._jobs, self._mount_points)
        if unsafe is not None:
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=unsafe[1]))
            return None
        if st.has_socket:
            self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason="holds a Unix socket"))
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
        """Job trees on tmpfs; the rules live in `shm_trees.py` (docs/adr/node_disk_retention_adr.md)."""
        policy = ShmTreePolicy(self._s, self._p, self._gate, self.skipped, self._now, self._open | self._mounts)
        for cand in policy.candidates():
            self._add(cand)

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
        # A unit inside another unit (uv `environments-v2/<hash>` under its cache) is already in the outer size.
        everything = [u for u, _ in sized + stale_sized]
        used = sum(
            st.size_bytes for u, st in sized + stale_sized if not any(o != u and is_within(u, o) for o in everything)
        )
        # Two needs: the budget counts every cache wherever it lives; the floor counts only bytes on `/`.
        need_budget = max(used - s.budget_bytes, 0)
        need_floor = max(s.floor_bytes - (free + freed_on_root), 0)
        if need_budget == 0 and need_floor == 0:
            return used
        gained_budget = gained_floor = 0

        def met() -> bool:
            return gained_budget >= need_budget and gained_floor >= need_floor

        def useless(path: str) -> bool:
            # Once the budget is met, a cache on another filesystem cannot help the floor.
            return gained_budget >= need_budget and not self._path_on_root(path)

        cutoff = self._now - s.idle_hours * HOUR
        for path, _ in sorted(stale_sized, key=lambda item: item[1].newest_ts):
            if met():
                break
            if useless(path):
                continue
            if matches_any(path, s.protected_globs) or in_use(path, self._mounts):
                continue
            unsafe = unsafe_reason(s, p.fs, path, self._jobs, self._mount_points, whole_path_resolves=True)
            if unsafe is not None:
                self.skipped.append(Skipped(path=path, size_bytes=0, reason=unsafe[1]))
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
                gained_budget += found.size_bytes
                gained_floor += found.size_bytes if self._path_on_root(path) else 0
        chosen: list[str] = []
        for path, st in sorted(sized, key=lambda item: item[1].newest_ts):
            if met():
                break
            if useless(path):
                continue
            if any(is_within(path, c) or is_within(c, path) for c in chosen):
                # Nested in (or holding) a unit already chosen: its bytes are counted once, and a uv cache keeps
                # its archive while its idle environments go (docs/adr/node_disk_retention_adr.md).
                reason = "nested with a cache unit already chosen"
                self.skipped.append(Skipped(path=path, size_bytes=st.size_bytes, reason=reason))
                continue
            cand = self._gate(
                path, Category.TOOL_CACHE, s.idle_hours * HOUR, "least recently used tool cache over budget or floor"
            )
            if cand is not None:
                self.candidates.append(cand)
                chosen.append(path)
                gained_budget += cand.size_bytes
                gained_floor += cand.size_bytes if self._path_on_root(path) else 0
        return used

    def _docker(self) -> None:
        d, days = self._p.docker, self._s.docker_build_cache_days
        # A drifted or missing protected image blocks every image prune and is reported as a failure.
        self._image_violations = protected_image_violations(self._s, d)
        dangling = d.dangling_images_reclaimable()
        if self._image_violations:
            for line in self._image_violations:
                self.skipped.append(Skipped(path="docker:dangling-images", size_bytes=dangling, reason=line))
        elif dangling > 0:
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
