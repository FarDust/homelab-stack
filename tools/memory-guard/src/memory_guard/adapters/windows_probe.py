"""Windows readings: GetPerformanceInfo owns commit and the non-paged pool (psutil exposes neither)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import psutil

from memory_guard.domain.errors import ProbeError
from memory_guard.domain.models import MemorySample, ProcessUsage


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


class WindowsMemoryProbe:
    def sample(self) -> MemorySample:
        if sys.platform != "win32":
            raise ProbeError("GetPerformanceInfo is only available on Windows")
        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.WinDLL("psapi", use_last_error=True).GetPerformanceInfo(ctypes.byref(info), info.cb):
            raise ProbeError(f"GetPerformanceInfo failed (winerror {ctypes.get_last_error()})")
        page = info.PageSize
        if page <= 0 or info.CommitLimit <= 0:
            raise ProbeError("GetPerformanceInfo returned a zero page size or commit limit")
        try:
            free_ram = psutil.virtual_memory().available
        except (OSError, psutil.Error) as exc:
            raise ProbeError(f"psutil could not read available RAM: {exc}") from exc
        return MemorySample(info.CommitTotal * page, info.CommitLimit * page, free_ram, info.KernelNonpaged * page)


class PsutilProcessLister:
    def top_by_private_bytes(self, limit: int) -> tuple[list[ProcessUsage], int]:
        rows: list[ProcessUsage] = []
        skipped = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                private = proc.memory_info().private
            except (psutil.Error, AttributeError):
                skipped += 1
                continue
            rows.append(ProcessUsage(proc.info["pid"], proc.info["name"] or "?", private))
        if not rows:
            raise ProbeError("no process private bytes could be read")
        rows.sort(key=lambda r: r.private_bytes, reverse=True)
        return rows[:limit], skipped


class PsutilVmmemProbe:
    """Private bytes of the WSL VM process (`vmmemWSL`, or `vmmem` on older WSL builds)."""

    NAMES = ("vmmemwsl", "vmmem")

    def private_bytes(self) -> int:
        total, found = 0, False
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() not in self.NAMES:
                continue
            try:
                total += proc.memory_info().private
            except psutil.Error as exc:
                raise ProbeError(f"cannot read private bytes of {proc.info['name']}: {exc}") from exc
            found = True
        if not found:
            raise ProbeError("vmmemWSL process not found although the distro is running")
        return total
