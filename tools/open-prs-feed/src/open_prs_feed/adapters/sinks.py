"""Atomic file sinks: a local directory, or a directory on another host over OpenSSH."""

from __future__ import annotations

import os
import shlex
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from open_prs_feed.adapters.process import CommandRunner, tail
from open_prs_feed.domain.errors import SinkError

# Remote side: temp file in the target dir, size check, chmod, rename. Runs under POSIX sh.
_REMOTE_SCRIPT = (
    'set -eu; d=$1; n=$2; want=$3; umask 022; t=$(mktemp "$d/.$n.XXXXXX"); '
    'trap \'rm -f "$t"\' EXIT; cat >"$t"; got=$(wc -c <"$t"); '
    'if [ "$got" -ne "$want" ]; then echo "size $got != $want" >&2; exit 3; fi; '
    'chmod 0644 "$t"; mv -f "$t" "$d/$n"; trap - EXIT'
)


class LocalAtomicSink:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def describe(self, name: str) -> str:
        return str(self._dir / name)

    def write(self, name: str, data: bytes) -> None:
        if not self._dir.is_dir():
            raise SinkError(f"output directory {self._dir} does not exist")
        target = self._dir / name
        fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=self._dir)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            if os.path.getsize(tmp) != len(data):
                raise SinkError(f"{tmp}: wrote {os.path.getsize(tmp)} bytes, expected {len(data)}")
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
        except OSError as exc:
            raise SinkError(f"writing {target}: {exc}") from exc
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class SshAtomicSink:
    """Streams the bytes to `ssh <host> sh -c <script>`; the rename happens on the remote filesystem."""

    def __init__(
        self,
        runner: CommandRunner,
        ssh_command: Sequence[str],
        host: str,
        directory: PurePosixPath,
        timeout_s: float,
    ) -> None:
        self._runner = runner
        self._ssh = list(ssh_command)
        self._host = host
        self._dir = directory
        self._timeout_s = timeout_s

    def describe(self, name: str) -> str:
        return f"{self._host}:{self._dir / name}"

    def write(self, name: str, data: bytes) -> None:
        remote = " ".join(
            shlex.quote(a) for a in ["sh", "-c", _REMOTE_SCRIPT, "_", str(self._dir), name, str(len(data))]
        )
        argv = [*self._ssh, "-o", "BatchMode=yes", self._host, remote]
        try:
            res = self._runner.run(argv, data, self._timeout_s)
        except FileNotFoundError as exc:
            raise SinkError(f"{self._ssh[0]} not found while writing {self.describe(name)}") from exc
        except TimeoutError as exc:
            raise SinkError(f"writing {self.describe(name)}: {exc}") from exc
        if res.returncode != 0:
            raise SinkError(
                f"writing {self.describe(name)} exited {res.returncode}: {tail(res.stderr) or '(no stderr)'}"
            )
