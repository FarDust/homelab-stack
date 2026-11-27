"""Small JSON state file, replaced atomically."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from memory_guard.domain.errors import StateError
from memory_guard.domain.models import Condition, ConditionState, GuardState


class JsonStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> GuardState:
        if not self._path.exists():
            return GuardState()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            state = GuardState()
            for cond in Condition:
                row = raw[cond.value]
                last = row["last_alert"]
                state.conditions[cond] = ConditionState(
                    int(row["consecutive"]), bool(row["active"]), datetime.fromisoformat(last) if last else None
                )
            return state
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StateError(
                f"state file {self._path} is unreadable or malformed ({exc!r}); delete it to reset"
            ) from exc

    def save(self, state: GuardState) -> None:
        raw = {
            c.value: {
                "consecutive": s.consecutive,
                "active": s.active,
                "last_alert": s.last_alert.isoformat() if s.last_alert else None,
            }
            for c, s in state.conditions.items()
        }
        tmp = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8", newline="\n")
            os.replace(tmp, self._path)
        except OSError as exc:
            raise StateError(f"cannot write state file {self._path}: {exc}") from exc
