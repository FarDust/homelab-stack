"""Open pull requests from a JSON file that a GitHub-capable job writes; as decided in docs/adr/node_disk_retention_adr.md."""

from __future__ import annotations

import json
from pathlib import Path

from node_retention.domain.ports import Clock


class OpenPrsFile:
    """`numbers()` reads `[201, 382]`. Missing, stale or malformed files answer None (unknown), never an empty set."""

    def __init__(self, path: Path | None, max_age_s: float, clock: Clock) -> None:
        self._path = path
        self._max_age_s = max_age_s
        self._clock = clock

    def numbers(self) -> set[int] | None:
        if self._path is None:
            return None
        try:
            age = self._clock.now() - self._path.stat().st_mtime
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if age > self._max_age_s or age < -60 or not isinstance(data, list):
            return None
        if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in data):
            return None
        return set(data)
