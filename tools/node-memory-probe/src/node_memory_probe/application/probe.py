"""One probe run: pick the processes, classify their memory, compute kernel rates, decide on a snapshot.

Read-only by design: the probe reads /proc, cgroupfs and jcmd answers and writes only its own state, the
textfile and snapshots. Decision record: docs/adr/node_memory_probe_adr.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from node_memory_probe.application.jvm import is_jvm, layout_from_flags, layout_with_jcmd
from node_memory_probe.application.snapshot import build_snapshot, snapshot_name
from node_memory_probe.domain.kernel import TriggerPolicy, counter_rates, rate, snapshot_reasons
from node_memory_probe.domain.models import CgroupMemory, KernelSample, ProcessBrief, ProcessMemory
from node_memory_probe.domain.ports import (
    Clock,
    ContainerDirectory,
    ContainerDirectoryError,
    JvmTool,
    KernelSource,
    ProcessGone,
    ProcessUnreadable,
    ProcSource,
    SnapshotStore,
    StateStore,
)
from node_memory_probe.domain.regions import summarize

STATE_VERSION = 1
# Processes whose presence explains a metadata walk (dentry/inode slab growth); counted every run.
SCANNER_COMMS = frozenset({"du", "find", "ncdu", "rsync", "rg", "updatedb", "tar", "restic", "borg", "fd"})


@dataclass(frozen=True, slots=True)
class ProbeOptions:
    host: str
    jvm_containers: tuple[str, ...]
    aliases: dict[str, str]
    top_swap_processes: int
    top_mappings: int
    top_cgroups: int
    top_readers: int
    cpu_psi_skip_avg10: float
    trigger: TriggerPolicy
    snapshot_max_age_s: float
    snapshot_budget_bytes: int


@dataclass(frozen=True, slots=True)
class Ports:
    procs: ProcSource
    kernel: KernelSource
    jcmd: JvmTool
    containers: ContainerDirectory
    state: StateStore
    snapshots: SnapshotStore
    clock: Clock


@dataclass(frozen=True, slots=True)
class CgroupRow:
    label: str
    cgroup: CgroupMemory
    swap_change_per_s: float | None
    pgscan_per_s: float | None


@dataclass(slots=True)
class ProbeResult:
    host: str
    timestamp: float
    kernel: KernelSample
    rates: dict[str, float]
    processes: list[ProcessMemory]
    cgroups: list[CgroupRow]
    readers: list[tuple[str, float]]
    scanners: dict[str, int]
    skipped: list[str] = field(default_factory=list)
    snapshot_reasons: list[str] = field(default_factory=list)
    snapshot_file: str | None = None
    snapshot_bytes_kept: int | None = None
    snapshots_removed: int = 0
    duration_s: float = 0.0


class Probe:
    def __init__(self, ports: Ports, options: ProbeOptions) -> None:
        self._p = ports
        self._o = options

    def run(self, *, dry_run: bool = False) -> ProbeResult:
        started = self._p.clock.monotonic()
        now = self._p.clock.now()
        state = self._p.state.load()
        if state.get("version") != STATE_VERSION:
            state = {"version": STATE_VERSION}
        kernel = self._p.kernel.sample()
        elapsed = now - float(state["ts"]) if "ts" in state else 0.0
        rates = counter_rates(state.get("vmstat", {}), kernel.vmstat, elapsed)
        skipped: list[str] = []
        cpu = kernel.pressure["cpu"].some_avg10
        deep = cpu < self._o.cpu_psi_skip_avg10
        if not deep:
            skipped.append(f"cpu PSI some avg10 {cpu:.1f} >= {self._o.cpu_psi_skip_avg10:.1f}")

        briefs = self._p.procs.processes()
        resolved: dict[str, str] = {}
        try:
            resolved = self._p.containers.resolve(self._o.jvm_containers) if self._o.jvm_containers else {}
        except ContainerDirectoryError as exc:
            skipped.append(f"container names unavailable: {exc}")
        primaries = self._primaries(briefs, resolved)
        selected = primaries + self._top_swap(briefs, {b.pid for b in primaries})
        cgroups = self._p.kernel.cgroups()
        top_cgroups = sorted(cgroups, key=lambda c: (-c.swap_current, c.path))[: self._o.top_cgroups]
        ids = {b.container_id for b in selected if b.container_id} | {c.container_id for c in top_cgroups if c.container_id}
        names: dict[str, str] = {}
        try:
            names = self._p.containers.names(sorted(ids)) if ids else {}
        except ContainerDirectoryError as exc:
            skipped.append(f"container names unavailable: {exc}")
        names.update({cid: name for name, cid in resolved.items()})

        jvm_cache: dict[str, Any] = state.get("jvm_ranges", {})
        live_keys = {f"{b.pid}:{b.start_ticks}" for b in briefs}
        jvm_cache = {k: v for k, v in jvm_cache.items() if k in live_keys}
        primary_pids = {b.pid for b in primaries}
        memories = [
            self._process(b, names, b.pid in primary_pids, deep, jvm_cache, kernel) for b in selected
        ]
        _dedupe_labels(memories)

        cgroup_rows = self._cgroup_rows(top_cgroups, names, state.get("cgroups", {}), elapsed)
        io_now = self._p.procs.read_bytes()
        readers = _top_readers(state.get("io", {}), io_now, elapsed, self._o.top_readers)
        scanners: dict[str, int] = {}
        for b in briefs:
            if b.comm in SCANNER_COMMS:
                scanners[b.comm] = scanners.get(b.comm, 0) + 1

        result = ProbeResult(
            self._o.host, now, kernel, rates, memories, cgroup_rows, readers, scanners, skipped=skipped
        )
        swap_free = kernel.meminfo.get("SwapFree", 0)
        result.snapshot_reasons = snapshot_reasons(
            self._o.trigger,
            swap_free,
            kernel.meminfo.get("SwapTotal", 0),
            rates.get("pswpout"),
            now,
            state.get("last_swap_free_snapshot"),
        )
        if result.snapshot_reasons and not dry_run:
            name = snapshot_name(now)
            self._p.snapshots.write(name, build_snapshot(result, self._o.top_mappings))
            result.snapshot_file = name
            if any(r.startswith("SwapFree") for r in result.snapshot_reasons):
                state["last_swap_free_snapshot"] = now
        if not dry_run:
            removed, kept = self._p.snapshots.enforce_retention(
                self._o.snapshot_max_age_s, self._o.snapshot_budget_bytes, now
            )
            result.snapshots_removed, result.snapshot_bytes_kept = removed, kept
            state.update(
                ts=now,
                vmstat=kernel.vmstat,
                cgroups={c.path: [c.swap_current, c.pgscan] for c in cgroups},
                io={f"{pid}:{ticks}": [comm, value] for (pid, ticks), (comm, value) in io_now.items()},
                jvm_ranges=jvm_cache,
            )
            self._p.state.save(state)
        result.duration_s = self._p.clock.monotonic() - started
        return result

    def _primaries(self, briefs: list[ProcessBrief], resolved: dict[str, str]) -> list[ProcessBrief]:
        """The largest JVM of every configured container; always probed, even with nothing in swap."""
        out: list[ProcessBrief] = []
        for name in self._o.jvm_containers:
            cid = resolved.get(name)
            if cid is None:
                continue
            jvms = [b for b in briefs if b.container_id == cid and b.comm == "java"]
            if jvms:
                out.append(max(jvms, key=lambda b: (b.vm_rss + b.vm_swap, -b.pid)))
        return out

    def _top_swap(self, briefs: list[ProcessBrief], exclude: set[int]) -> list[ProcessBrief]:
        holders = [b for b in briefs if b.vm_swap > 0 and b.pid not in exclude]
        holders.sort(key=lambda b: (-b.vm_swap, b.pid))
        return holders[: self._o.top_swap_processes]

    def _process(
        self,
        brief: ProcessBrief,
        names: dict[str, str],
        primary: bool,
        deep: bool,
        jvm_cache: dict[str, Any],
        kernel: KernelSample,
    ) -> ProcessMemory:
        container = names.get(brief.container_id, brief.container_id[:12]) if brief.container_id else ""
        label = self._o.aliases.get(container, container) if container else f"host/{brief.comm}"
        memory = ProcessMemory(brief, label, container, is_jvm=brief.comm == "java", primary=primary)
        if not deep:
            return memory
        try:
            args = self._p.procs.cmdline(brief.pid)
            mappings = self._p.procs.mappings(brief.pid)
            sps = self._p.procs.stack_pointers(brief.pid)
        except ProcessGone as exc:
            memory.errors.append(f"process gone while reading: {exc}")
            return memory
        except ProcessUnreadable as exc:
            memory.errors.append(f"read refused: {exc}")
            return memory
        memory.is_jvm = is_jvm(brief, args)
        if memory.is_jvm:
            limit = self._p.kernel.memory_limit(brief.cgroup) or kernel.meminfo.get("MemTotal")
            if primary:
                memory.layout, memory.jcmd_ok = layout_with_jcmd(
                    self._p.jcmd, brief, mappings, args, limit, jvm_cache, memory.errors
                )
            else:
                memory.layout = layout_from_flags(mappings, args, limit)
        memory.regions, memory.top_mappings = summarize(mappings, memory.layout, sps, self._o.top_mappings)
        return memory

    def _cgroup_rows(
        self, top: list[CgroupMemory], names: dict[str, str], previous: dict[str, Any], elapsed: float
    ) -> list[CgroupRow]:
        rows = []
        for c in top:
            prev = previous.get(c.path)
            swap_change = None
            pgscan = None
            if prev is not None and elapsed > 0:
                swap_change = (c.swap_current - int(prev[0])) / elapsed
                pgscan = rate(int(prev[1]), c.pgscan, elapsed)
            name = names.get(c.container_id, "") if c.container_id else ""
            label = self._o.aliases.get(name, name) if name else c.path
            rows.append(CgroupRow(label, c, swap_change, pgscan))
        return rows


def _dedupe_labels(memories: list[ProcessMemory]) -> None:
    """Two selected processes in one container keep distinct labels: add the comm, then the pid."""
    seen: dict[str, int] = {}
    for m in memories:
        seen[m.label] = seen.get(m.label, 0) + 1
    for m in memories:
        if seen[m.label] > 1:
            m.label = f"{m.label}/{m.brief.comm}"
    final: dict[str, int] = {}
    for m in memories:
        final[m.label] = final.get(m.label, 0) + 1
    for m in memories:
        if final[m.label] > 1:
            m.label = f"{m.label}/{m.brief.pid}"


def _top_readers(
    previous: dict[str, Any], current: dict[tuple[int, int], tuple[str, int]], elapsed: float, top: int
) -> list[tuple[str, float]]:
    """Processes with the most storage reads since the last run (bytes per second), by comm."""
    if elapsed <= 0:
        return []
    by_comm: dict[str, float] = {}
    for (pid, ticks), (comm, value) in current.items():
        prev = previous.get(f"{pid}:{ticks}")
        if prev is None:
            continue
        per_s = rate(int(prev[1]), value, elapsed)
        if per_s:
            by_comm[comm] = by_comm.get(comm, 0.0) + per_s
    return sorted(by_comm.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
