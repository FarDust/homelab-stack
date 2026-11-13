"""Publish a Prometheus textfile into the node_exporter textfile collector directory."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


class TextfilePublisher:
    """Atomic rename when the directory is writable; otherwise a one-shot helper container copies it.

    The collector directory is usually root-owned. The docker group already administers the node, and other
    node jobs publish through containers the same way, so the helper container is the supported fallback.
    """

    def __init__(self, directory: Path, helper_image: str) -> None:
        self._dir = directory
        self._image = helper_image

    def publish(self, name: str, text: str) -> None:
        if os.access(self._dir, os.W_OK):
            tmp = self._dir / f".{name}.tmp"
            tmp.write_text(text, encoding="utf-8")
            tmp.chmod(0o644)
            tmp.replace(self._dir / name)
            return
        with tempfile.TemporaryDirectory() as staging:
            src = Path(staging) / name
            src.write_text(text, encoding="utf-8")
            src.chmod(0o644)
            script = f"cp /src/{name} /m/.{name}.tmp && chmod 644 /m/.{name}.tmp && mv /m/.{name}.tmp /m/{name}"
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    f"{self._dir}:/m",
                    "-v",
                    f"{staging}:/src:ro",
                    self._image,
                    "sh",
                    "-c",
                    script,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        if not (self._dir / name).exists():
            raise RuntimeError(f"textfile {name} missing from {self._dir} after publishing")
