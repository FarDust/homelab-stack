"""WSL control through `wsl.exe`: list running distros (never starts one), drop the guest page cache, write a textfile."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable

from memory_guard.domain.errors import PublishError, ReclaimError

Runner = Callable[..., subprocess.CompletedProcess[bytes]]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DROP_SCRIPT = "sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory || true"
LIST_TIMEOUT_S = 15.0


def _decode(raw: bytes) -> str:
    # `wsl.exe --list` writes UTF-16LE; command output from the guest is UTF-8.
    return raw.decode("utf-16-le" if b"\x00" in raw else "utf-8", errors="replace").replace("\x00", "").lstrip("﻿")


class WslCli:
    def __init__(self, distro: str, timeout_s: float, runner: Runner = subprocess.run) -> None:
        self._distro, self._timeout, self._run = distro, timeout_s, runner

    def _exec(self, argv: list[str], timeout: float, what: str) -> subprocess.CompletedProcess[bytes]:
        try:
            return self._run(argv, capture_output=True, timeout=timeout, check=False, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as exc:
            raise ReclaimError(
                f"{what} timed out after {timeout:.0f}s; check `wsl --list --running` and the WSL service"
            ) from exc
        except OSError as exc:
            raise ReclaimError(f"{what} could not run wsl.exe ({exc}); check that WSL is installed") from exc

    def is_running(self) -> bool:
        done = self._exec(["wsl.exe", "--list", "--running", "--quiet"], LIST_TIMEOUT_S, "wsl --list --running")
        if done.returncode != 0:
            raise ReclaimError(
                f"`wsl --list --running` exited {done.returncode}: {_decode(done.stderr).strip()[:300]}; "
                "check the WSL service"
            )
        names = {line.strip().lower() for line in _decode(done.stdout).splitlines() if line.strip()}
        return self._distro.lower() in names

    def drop_cache(self) -> None:
        argv = ["wsl.exe", "-d", self._distro, "-u", "root", "--", "sh", "-c", DROP_SCRIPT]
        done = self._exec(argv, self._timeout, f"WSL cache drop in {self._distro!r}")
        if done.returncode != 0:
            raise ReclaimError(
                f"WSL cache drop in {self._distro!r} exited {done.returncode}: {_decode(done.stderr).strip()[:300]}; "
                f"check that the distro runs and that root is available (`wsl -d {self._distro} -u root -- id`)"
            )


class WslTextfileWriter:
    """Writes a node-exporter textfile inside the guest: content on stdin to `cat > tmp && mv tmp final` as root."""

    def __init__(self, distro: str, path: str, timeout_s: float, runner: Runner = subprocess.run) -> None:
        self._distro, self._path, self._timeout, self._run = distro, path, timeout_s, runner

    def argv(self) -> list[str]:
        tmp = shlex.quote(self._path + ".tmp")
        script = f"cat > {tmp} && mv {tmp} {shlex.quote(self._path)}"
        return ["wsl.exe", "-d", self._distro, "-u", "root", "--", "sh", "-c", script]

    def write(self, content: str) -> None:
        what = f"textfile write {self._path!r} in {self._distro!r}"
        try:
            done = self._run(
                self.argv(),
                input=content.encode("utf-8"),
                capture_output=True,
                timeout=self._timeout,
                check=False,
                creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise PublishError(f"{what} timed out after {self._timeout:.0f}s; check the WSL service") from exc
        except OSError as exc:
            raise PublishError(f"{what} could not run wsl.exe ({exc}); check that WSL is installed") from exc
        if done.returncode != 0:
            raise PublishError(
                f"{what} exited {done.returncode}: {_decode(done.stderr).strip()[:300]}; check that the textfile "
                "collector directory exists in the guest and root is available"
            )
