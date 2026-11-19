"""Linux /proc and cgroup v2 readers. smaps parsing is psutil's; the rest are one-line files psutil does not cover."""

from __future__ import annotations

import os
import re
from pathlib import Path

import psutil

from node_memory_probe.domain.models import CgroupMemory, KernelSample, Mapping, Pressure, ProcessBrief
from node_memory_probe.domain.ports import ProcessGone, ProcessUnreadable

_CONTAINER = re.compile(r"(?:docker-|/docker/)([0-9a-f]{64})(?:\.scope)?")
_VANISHED = (FileNotFoundError, ProcessLookupError)
CGROUP_MAX_DEPTH = 6


def container_id(cgroup: str) -> str | None:
    match = _CONTAINER.search(cgroup)
    return match.group(1) if match else None


def parse_status(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out[key] = value.strip()
    return out


def _kib(value: str | None) -> int:
    return int(value.split()[0]) * 1024 if value else 0


def parse_stat_start_ticks(text: str) -> int:
    """Field 22 of /proc/<pid>/stat; the comm field may hold spaces and parentheses, so split after the last ')'."""
    rest = text[text.rindex(")") + 2 :].split()
    return int(rest[19])


def parse_pressure(text: str) -> Pressure:
    values: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        kind, *pairs = line.split()
        values[kind] = {k: float(v) for k, v in (p.split("=") for p in pairs)}
    some = values["some"]
    full = values.get("full")
    return Pressure(some["avg10"], some["avg60"], full["avg10"] if full else None, full["avg60"] if full else None)


def parse_meminfo(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        parts = value.split()
        if not parts:
            continue
        out[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
    return out


def parse_flat_counters(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            out[parts[0]] = int(parts[1])
    return out


def parse_stack_pointer(text: str) -> int | None:
    """/proc/<pid>/task/<tid>/syscall: "nr a1..a6 sp pc" or "-1 sp pc" when blocked; "running" otherwise."""
    parts = text.split()
    if len(parts) < 3 or parts[0] == "running":
        return None
    return int(parts[-2], 16)


class ProcFs:
    def __init__(self, proc_root: Path, cgroup_root: Path) -> None:
        self._proc = proc_root
        self._cg = cgroup_root

    def _pids(self) -> list[int]:
        return [int(n) for n in os.listdir(self._proc) if n.isdigit()]

    def processes(self) -> list[ProcessBrief]:
        out: list[ProcessBrief] = []
        for pid in self._pids():
            base = self._proc / str(pid)
            try:
                status = parse_status((base / "status").read_text())
                ticks = parse_stat_start_ticks((base / "stat").read_text())
                cgroup = (base / "cgroup").read_text().strip().split("::", 1)[-1]
            except _VANISHED:
                continue
            uid = int(status["Uid"].split()[0])
            gid = int(status["Gid"].split()[0])
            ns_pid = int(status.get("NSpid", str(pid)).split()[-1])
            out.append(
                ProcessBrief(
                    pid=pid,
                    comm=status["Name"],
                    vm_rss=_kib(status.get("VmRSS")),  # kernel threads have no Vm* lines
                    vm_swap=_kib(status.get("VmSwap")),
                    uid=uid,
                    gid=gid,
                    ns_pid=ns_pid,
                    start_ticks=ticks,
                    cgroup=cgroup,
                    container_id=container_id(cgroup),
                )
            )
        return out

    def mappings(self, pid: int) -> list[Mapping]:
        try:
            rows = psutil.Process(pid).memory_maps(grouped=False)
        except psutil.NoSuchProcess as exc:
            raise ProcessGone(f"pid {pid}") from exc
        except psutil.AccessDenied as exc:
            raise ProcessUnreadable(f"/proc/{pid}/smaps needs ptrace read access (run the unit as root)") from exc
        out = []
        for row in rows:
            start, _, end = row.addr.partition("-")
            out.append(Mapping(int(start, 16), int(end, 16), row.perms, row.path, row.rss, row.pss, row.swap))
        return out

    def cmdline(self, pid: int) -> list[str]:
        try:
            raw = (self._proc / str(pid) / "cmdline").read_bytes()
        except _VANISHED as exc:
            raise ProcessGone(f"pid {pid}") from exc
        return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]

    def stack_pointers(self, pid: int) -> list[int]:
        task_dir = self._proc / str(pid) / "task"
        try:
            tids = os.listdir(task_dir)
        except _VANISHED as exc:
            raise ProcessGone(f"pid {pid}") from exc
        except PermissionError as exc:
            raise ProcessUnreadable(f"{task_dir} listing refused") from exc
        sps: list[int] = []
        for tid in tids:
            try:
                sp = parse_stack_pointer((task_dir / tid / "syscall").read_text())
            except _VANISHED:
                continue  # the thread ended between the listing and the read
            except PermissionError as exc:
                raise ProcessUnreadable(f"{task_dir}/{tid}/syscall needs ptrace attach access") from exc
            if sp is not None:
                sps.append(sp)
        return sps

    def read_bytes(self) -> dict[tuple[int, int], tuple[str, int]]:
        out: dict[tuple[int, int], tuple[str, int]] = {}
        for pid in self._pids():
            base = self._proc / str(pid)
            try:
                io = parse_flat_counters((base / "io").read_text().replace(":", ""))
                stat = (base / "stat").read_text()
            except _VANISHED:
                continue
            except PermissionError:
                continue  # unprivileged dry runs cannot read other users' io; the root unit can
            comm = stat[stat.index("(") + 1 : stat.rindex(")")]
            out[(pid, parse_stat_start_ticks(stat))] = (comm, io["read_bytes"])
        return out

    def sample(self) -> KernelSample:
        pressure = {
            name: parse_pressure((self._proc / "pressure" / name).read_text()) for name in ("cpu", "memory", "io")
        }
        return KernelSample(
            meminfo=parse_meminfo((self._proc / "meminfo").read_text()),
            vmstat=parse_flat_counters((self._proc / "vmstat").read_text()),
            pressure=pressure,
        )

    def cgroups(self) -> list[CgroupMemory]:
        """Leaf cgroups with a swap counter; parents would double count their children."""
        out: list[CgroupMemory] = []
        root = str(self._cg)
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth >= CGROUP_MAX_DEPTH:
                dirnames.clear()
            if dirnames or "memory.swap.current" not in filenames or rel == ".":
                continue
            base = Path(dirpath)
            try:
                stat = parse_flat_counters((base / "memory.stat").read_text())
                swap = int((base / "memory.swap.current").read_text())
                current = int((base / "memory.current").read_text())
            except _VANISHED:
                continue
            out.append(
                CgroupMemory(
                    path=rel.replace(os.sep, "/"),
                    container_id=container_id(rel),
                    swap_current=swap,
                    memory_current=current,
                    pgscan=stat.get("pgscan", 0),
                    pgsteal=stat.get("pgsteal", 0),
                )
            )
        return out

    def memory_limit(self, cgroup: str) -> int | None:
        path = self._cg / cgroup.lstrip("/") / "memory.max"
        try:
            text = path.read_text().strip()
        except _VANISHED:
            return None
        return None if text == "max" else int(text)
