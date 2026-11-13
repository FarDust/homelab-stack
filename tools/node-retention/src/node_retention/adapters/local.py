"""Local filesystem, process table, ledger and clock adapters (Linux)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from node_retention.domain.models import StaleFiles, TreeStats


class LocalFileSystem:
    def children(self, path: str) -> list[str]:
        try:
            with os.scandir(path) as it:
                return sorted(entry.path for entry in it)
        except FileNotFoundError:
            return []

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def owned_by_current_user(self, path: str) -> bool:
        try:
            return os.lstat(path).st_uid == os.getuid()
        except FileNotFoundError:
            return False  # vanished while listing: another process cleaned it first

    def free_bytes(self, path: str) -> int:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize

    def stats(self, path: str) -> TreeStats:
        """Allocated size plus newest mtime and atime.

        Only regular files contribute an atime: listing a directory or following a symlink updates those
        timestamps, so counting them would make the scan itself look like a recent use. Hardlinked files
        are counted once (uv and npm caches hardlink heavily).
        """
        size, newest_m, newest_a = 0, 0.0, 0.0
        seen: set[tuple[int, int]] = set()
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            newest_m = max(newest_m, st.st_mtime)
            if stat.S_ISREG(st.st_mode):
                newest_a = max(newest_a, st.st_atime)
                if st.st_nlink > 1:
                    if (st.st_dev, st.st_ino) in seen:
                        continue
                    seen.add((st.st_dev, st.st_ino))
            size += st.st_blocks * 512
            if is_dir:
                try:
                    with os.scandir(current) as it:
                        stack.extend(entry.path for entry in it)
                except (PermissionError, FileNotFoundError):
                    continue
        return TreeStats(size_bytes=size, newest_mtime=newest_m, newest_atime=newest_a)

    def _stale_paths(self, path: str, cutoff_ts: float, open_paths: set[str]) -> Iterator[tuple[str, os.stat_result]]:
        """Yield (file, stat) for regular singly linked files not read or written since the cutoff."""
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                continue
            for entry in entries:
                try:
                    st = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    stack.append(entry.path)
                elif (
                    stat.S_ISREG(st.st_mode)
                    and st.st_nlink == 1
                    and max(st.st_mtime, st.st_atime) < cutoff_ts
                    and entry.path not in open_paths
                ):
                    yield entry.path, st

    def stale_files(self, path: str, cutoff_ts: float) -> StaleFiles:
        size = count = 0
        for _, st in self._stale_paths(path, cutoff_ts, set()):
            size += st.st_blocks * 512
            count += 1
        return StaleFiles(size_bytes=size, count=count)

    def prune_stale_files(self, path: str, cutoff_ts: float, open_paths: set[str]) -> int:
        freed = 0
        for file_path, st in self._stale_paths(path, cutoff_ts, open_paths):
            try:
                os.unlink(file_path)
            except (FileNotFoundError, PermissionError):
                continue  # gone already, or owned by another user: left for the next run
            freed += st.st_blocks * 512
        return freed

    def remove(self, path: str) -> None:
        if os.path.islink(path) or os.path.isfile(path):
            os.unlink(path)
        else:
            shutil.rmtree(path)


class ProcProcesses:
    def open_paths(self) -> set[str]:
        paths: set[str] = set()
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            base = f"/proc/{pid}"
            try:
                paths.add(os.readlink(f"{base}/cwd"))
                for fd in os.listdir(f"{base}/fd"):
                    paths.add(os.readlink(f"{base}/fd/{fd}"))
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
        return {p for p in paths if p.startswith("/")}

    def is_alive(self, pid: int) -> bool:
        return Path(f"/proc/{pid}").exists()


class JsonlLedger:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, row: dict[str, object]) -> None:
        line = json.dumps(row, separators=(",", ":")) + "\n"
        # One O_APPEND write per row; the ledger is advisory and never a lock.
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)


class SystemClock:
    def now(self) -> float:
        return time.time()
