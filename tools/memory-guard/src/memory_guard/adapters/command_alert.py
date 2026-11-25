"""Alert path: an external command (the agent-bridge `post`), with `{message}` replaced in its argument list."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from memory_guard.domain.errors import AlertError

Runner = Callable[..., subprocess.CompletedProcess[str]]
PLACEHOLDER = "{message}"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class CommandAlertSink:
    def __init__(self, command: list[str], timeout_s: float, confirm: str, runner: Runner = subprocess.run) -> None:
        if not any(PLACEHOLDER in a for a in command):
            raise AlertError(f"alert command must contain the {PLACEHOLDER} placeholder")
        self._command, self._timeout, self._confirm, self._run = command, timeout_s, confirm, runner

    def send(self, text: str) -> None:
        argv = [a.replace(PLACEHOLDER, text) for a in self._command]
        try:
            done = self._run(
                argv, capture_output=True, text=True, timeout=self._timeout, check=False, creationflags=_NO_WINDOW
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AlertError(f"alert command {self._command[0]!r} failed to run: {exc}") from exc
        if done.returncode != 0:
            raise AlertError(f"alert command exited {done.returncode}: {done.stderr.strip()[:300]}")
        if self._confirm not in done.stdout:
            raise AlertError(f"alert command exited 0 without the {self._confirm!r} receipt in its output")
