#!/usr/bin/env bash
set -euo pipefail

exec python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


ASSIGNMENT = re.compile(
    rb"^(?:export[ \t]+)?GRAFANA_CONFIG_VERSION=([1-9][0-9]*)([ \t]*)(\r?\n)?$"
)
ASSIGNMENT_PREFIX = re.compile(rb"^(?:export[ \t]+)?GRAFANA_CONFIG_VERSION(?:[ \t]*=|[ \t]*$)")


def positive_integer(value: str) -> int:
    if not value.isdecimal() or int(value) < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return int(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage the scoped Grafana config version.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "bump"):
        command = commands.add_parser(name)
        command.add_argument("--env-file", type=Path, default=Path(".env"))
    commands.choices["init"].add_argument("--value", type=positive_integer, required=True)
    return parser.parse_args()


def update_env(path: Path, command: str, requested: int | None) -> int:
    try:
        source = path.read_bytes()
        source_stat = path.stat()
    except FileNotFoundError as error:
        raise SystemExit(f"environment file does not exist: {path}") from error

    lines = source.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[bytes]]] = []
    for index, line in enumerate(lines):
        if ASSIGNMENT_PREFIX.match(line):
            match = ASSIGNMENT.fullmatch(line)
            if match is None:
                raise SystemExit("GRAFANA_CONFIG_VERSION must be an exported positive integer")
            matches.append((index, match))

    if len(matches) > 1:
        raise SystemExit("GRAFANA_CONFIG_VERSION must appear exactly once")

    if command == "init":
        assert requested is not None
        if matches:
            existing = int(matches[0][1].group(1))
            if existing != requested:
                raise SystemExit("GRAFANA_CONFIG_VERSION already exists with a different value")
            return existing
        newline = b"\r\n" if b"\r\n" in source else b"\n"
        separator = b"" if not source or source.endswith((b"\n", b"\r")) else newline
        updated = source + separator + f"export GRAFANA_CONFIG_VERSION={requested}".encode() + newline
        version = requested
    else:
        if not matches:
            raise SystemExit("GRAFANA_CONFIG_VERSION is not initialized")
        index, match = matches[0]
        version = int(match.group(1)) + 1
        ending = match.group(3) or b""
        lines[index] = f"export GRAFANA_CONFIG_VERSION={version}".encode() + ending
        updated = b"".join(lines)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, stat.S_IMODE(source_stat.st_mode))
        os.chown(temporary_path, source_stat.st_uid, source_stat.st_gid)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return version


arguments = parse_args()
version = update_env(arguments.env_file, arguments.command, getattr(arguments, "value", None))
print(f"GRAFANA_CONFIG_VERSION={version}")
PY
