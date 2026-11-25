"""Subprocess runner shared by the gh source and the SSH sink."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], stdin: bytes | None, timeout_s: float) -> RunResult:
        """Run argv; raises FileNotFoundError when the binary is missing and TimeoutError on timeout."""
        ...


class SubprocessRunner:
    def run(self, argv: Sequence[str], stdin: bytes | None, timeout_s: float) -> RunResult:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            done = subprocess.run(
                list(argv),
                input=stdin if stdin is not None else b"",
                capture_output=True,
                timeout=timeout_s,
                check=False,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"{argv[0]} did not finish within {timeout_s:g} s") from exc
        return RunResult(done.returncode, done.stdout, done.stderr)


def tail(data: bytes, limit: int = 400) -> str:
    """Last bytes of a stream for a diagnostic, decoded leniently."""
    text = data.decode("utf-8", errors="replace").strip()
    return text[-limit:]
