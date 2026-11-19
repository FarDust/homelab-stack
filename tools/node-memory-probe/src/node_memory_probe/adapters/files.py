"""Local files the probe owns: its state, the textfile and the snapshots. Every write is a same-directory rename."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class StateCorrupt(RuntimeError):
    """The probe's own state file is not JSON; remove it to start a fresh rate baseline."""


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    # O_EXCL | O_NOFOLLOW: this runs as root, so a planted symlink at the temporary name must fail, not be followed.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    tmp.replace(path)


class JsonState:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StateCorrupt(f"{self._path} is not JSON ({exc}); remove it to reset the rate baseline") from exc
        if not isinstance(data, dict):
            raise StateCorrupt(f"{self._path} does not hold a JSON object")
        return data

    def save(self, state: dict[str, Any]) -> None:
        _atomic_write(self._path, json.dumps(state, separators=(",", ":")).encode("utf-8"), 0o600)


class Textfile:
    """node_exporter's textfile collector ignores dot files, so the temporary name is never scraped."""

    def __init__(self, directory: Path, name: str) -> None:
        if not name.endswith(".prom"):
            raise ValueError(f"textfile name must end in .prom: {name}")
        self._path = directory / name

    def publish(self, text: str) -> None:
        if not self._path.parent.is_dir():
            raise FileNotFoundError(f"textfile collector directory {self._path.parent} does not exist")
        _atomic_write(self._path, text.encode("utf-8"))


class SnapshotDir:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def write(self, name: str, payload: dict[str, Any]) -> int:
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        _atomic_write(self._dir / name, data)
        return len(data)

    def enforce_retention(self, max_age_s: float, budget_bytes: int, now: float) -> tuple[int, int]:
        if not self._dir.is_dir():
            return 0, 0
        files = sorted(
            ((p.stat().st_mtime, p.stat().st_size, p) for p in self._dir.glob("snapshot-*.json")),
            key=lambda t: t[0],
        )
        removed = 0
        kept: list[tuple[float, int, Path]] = []
        for mtime, size, path in files:
            if now - mtime > max_age_s:
                path.unlink(missing_ok=True)
                removed += 1
            else:
                kept.append((mtime, size, path))
        total = sum(size for _, size, _ in kept)
        while kept and total > budget_bytes:
            _, size, path = kept.pop(0)
            path.unlink(missing_ok=True)
            total -= size
            removed += 1
        return removed, total


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()
