"""Append-only JSONL log of cache-drop attempts; the rate limit reads it back."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from memory_guard.domain.errors import StateError
from memory_guard.domain.models import ReclaimRecord, ReclaimSnapshot

KEEP_LINES = 500
TRIM_AT = 1000


def _snap(s: ReclaimSnapshot | None) -> dict[str, int] | None:
    if s is None:
        return None
    return {"free_virtual": s.free_virtual, "free_ram": s.free_ram, "vmmem_private": s.vmmem_private}


def _unsnap(row: dict[str, int]) -> ReclaimSnapshot:
    return ReclaimSnapshot(row["free_virtual"], row["free_ram"], row["vmmem_private"])


class JsonlReclaimLog:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> list[ReclaimRecord]:
        if not self._path.exists():
            return []
        out: list[ReclaimRecord] = []
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                after = row["after"]
                out.append(
                    ReclaimRecord(
                        datetime.fromisoformat(row["at"]),
                        bool(row["ok"]),
                        _unsnap(row["before"]),
                        None if after is None else _unsnap(after),
                        row["error"],
                    )
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StateError(
                f"reclaim log {self._path} is unreadable or malformed ({exc!r}); delete it to reset"
            ) from exc
        return out

    def recent(self, since: datetime) -> list[ReclaimRecord]:
        return [r for r in self._read() if r.at >= since]

    def append(self, record: ReclaimRecord) -> None:
        row = {
            "at": record.at.isoformat(),
            "ok": record.ok,
            "before": _snap(record.before),
            "after": _snap(record.after),
            "error": record.error,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row) + "\n")
            lines = self._path.read_text(encoding="utf-8").splitlines()
            if len(lines) > TRIM_AT:
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8", newline="\n")
                tmp.replace(self._path)
        except OSError as exc:
            raise StateError(f"cannot write reclaim log {self._path}: {exc}") from exc
