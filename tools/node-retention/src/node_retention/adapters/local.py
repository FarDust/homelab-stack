"""Local filesystem, process table, ledger and clock adapters (Linux)."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from node_retention.domain.errors import LedgerUnreadableError
from node_retention.domain.models import StaleFiles, TreeStats

_OCTAL = re.compile(r"\\([0-7]{3})")


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

    def resolve(self, path: str) -> str:
        return os.path.realpath(path)

    def mount_points(self, mountinfo: str = "/proc/self/mountinfo") -> set[str]:
        points: set[str] = set()
        with open(mountinfo, encoding="utf-8") as handle:
            for line in handle:
                # Field 5 is the mount point, with spaces and tabs escaped as octal ( , 	).
                raw = line.split()[4]
                points.add(_OCTAL.sub(lambda m: chr(int(m.group(1), 8)), raw))
        return points

    def stats(self, path: str) -> TreeStats:
        """Allocated size plus newest mtime and atime.

        Only regular files contribute an atime: listing a directory or following a symlink updates those
        timestamps, so counting them would make the scan itself look like a recent use. Hardlinked files
        are counted once (uv and npm caches hardlink heavily).
        """
        size, newest_m, newest_a, has_socket = 0, 0.0, 0.0, False
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
            has_socket = has_socket or stat.S_ISSOCK(st.st_mode)
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
        return TreeStats(size_bytes=size, newest_mtime=newest_m, newest_atime=newest_a, has_socket=has_socket)

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
        """Remove a file, a symlink (never its target) or a tree.

        `shutil.rmtree` uses the fd-based implementation on Linux: it does not follow symlinks inside the tree
        and is not fooled by a directory swapped for a symlink mid-walk. Entries that another process removed
        concurrently are not an error; the caller verifies that the path is gone.
        """
        if os.path.islink(path) or not os.path.isdir(path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                return
            return

        def tolerate_vanished(func: object, failed: str, exc: BaseException) -> None:
            if not isinstance(exc, FileNotFoundError):
                raise exc

        shutil.rmtree(path, onexc=tolerate_vanished)


class ProcProcesses:
    def open_paths(self) -> set[str]:
        paths: set[str] = set()
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            base = f"/proc/{pid}"
            # Processes of other users (root, containers) are not readable; container mounts cover those.
            for link in ("cwd", "exe"):
                try:
                    paths.add(os.readlink(f"{base}/{link}"))
                except (PermissionError, FileNotFoundError, ProcessLookupError):
                    pass
            try:
                for fd in os.listdir(f"{base}/fd"):
                    paths.add(os.readlink(f"{base}/fd/{fd}"))
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                pass
            paths |= self._mapped_files(f"{base}/maps")
        return {p.removesuffix(" (deleted)") for p in paths if p.startswith("/")}

    @staticmethod
    def _mapped_files(maps: str) -> set[str]:
        """Files mapped into memory: interpreters and shared libraries running out of a cache directory."""
        found: set[str] = set()
        try:
            with open(maps, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    parts = line.split(maxsplit=5)
                    if len(parts) == 6 and parts[5].startswith("/"):
                        found.add(parts[5].rstrip("\n"))
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass
        return found

    def is_alive(self, pid: int) -> bool:
        return Path(f"/proc/{pid}").exists()


class JsonlLedger:
    """The node's append-only job ledger: written by every agent, read here to find running jobs."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache_key: tuple[int, int] | None = None
        self._cache: list[dict[str, object]] = []

    def rows(self) -> list[dict[str, object]]:
        """Parse the ledger, re-reading only when its size or mtime changed.

        Fails closed: a missing or unreadable file, or a malformed row, raises `LedgerUnreadableError`. The one
        exception is a final line without its newline, which is a row another agent is still appending.
        """
        try:
            st = self._path.stat()
            key = (st.st_size, st.st_mtime_ns)
            if key == self._cache_key:
                return self._cache
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerUnreadableError(f"job ledger {self._path} is unreadable: {exc}") from exc
        lines = text.split("\n")
        complete, tail = lines[:-1], lines[-1]
        rows: list[dict[str, object]] = []
        for number, line in enumerate(complete, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerUnreadableError(f"job ledger {self._path} line {number} is not JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise LedgerUnreadableError(f"job ledger {self._path} line {number} is not an object")
            rows.append(row)
        if tail.strip():
            try:
                row = json.loads(tail)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                pass  # torn final row of a concurrent append; it is complete on the next read
        self._cache_key, self._cache = key, rows
        return rows

    def append(self, row: dict[str, object]) -> None:
        line = json.dumps(row, separators=(",", ":")) + "\n"
        # One O_APPEND write per row; the ledger is advisory and never a lock.
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)


class SystemClock:
    def now(self) -> float:
        return time.time()
