"""Exercise the installed logrotate parser against disposable log families."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
POLICY = REPOSITORY / "host-config" / "logrotate" / "rsyslog.conf"
PREIMAGE = Path(__file__).parent / "fixtures" / "logrotate" / "rsyslog-size-override.conf"
LOG_NAMES = ("syslog", "kern.log", "auth.log")


@dataclass(frozen=True)
class NativeFixture:
    config: Path
    state: Path
    logs: tuple[Path, ...]
    state_digest: str
    log_digests: tuple[str, ...]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(directory: Path, *, legacy_size: bool = False) -> NativeFixture:
    log_directory = directory / "logs"
    log_directory.mkdir(mode=0o700)
    logs = tuple(log_directory / name for name in LOG_NAMES)
    for path in logs:
        path.write_text("synthetic diagnostic evidence\n", encoding="utf-8", newline="\n")
        path.chmod(0o600)
    state = directory / "status"
    state.write_text(
        "logrotate state -- version 2\n"
        + "".join(f'"{path.as_posix()}" 2000-1-1-0:0:0\n' for path in logs),
        encoding="utf-8",
        newline="\n",
    )
    state.chmod(0o600)
    source_path = PREIMAGE if legacy_size else POLICY
    source = source_path.read_text(encoding="utf-8")
    rendered = source.replace("/var/log/", log_directory.as_posix() + "/")
    # Debug mode must never point at real logs or execute the distribution helper.
    rendered = rendered.replace("/usr/lib/rsyslog/rsyslog-rotate", "false")
    if "/var/log/" in rendered or "/usr/lib/rsyslog/rsyslog-rotate" in rendered:
        raise RuntimeError("Synthetic logrotate fixture retained a production path")
    config = directory / "rsyslog.conf"
    config.write_text(rendered, encoding="utf-8", newline="\n")
    config.chmod(0o600)
    return NativeFixture(config, state, logs, _digest(state), tuple(map(_digest, logs)))


def _debug(fixture: NativeFixture) -> str:
    executable = shutil.which("logrotate")
    if executable is None:
        raise RuntimeError("Native logrotate is required for this regression check")
    result = subprocess.run(
        [executable, "--debug", "--state", str(fixture.state), str(fixture.config)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0 or "error:" in output.casefold() or "Handling 2 logs" not in output:
        raise RuntimeError(f"Native logrotate did not parse both fixture groups: {output}")
    return output


def _assert_untouched(fixture: NativeFixture) -> None:
    assert _digest(fixture.state) == fixture.state_digest
    assert tuple(map(_digest, fixture.logs)) == fixture.log_digests
    assert sorted(path.name for path in fixture.logs[0].parent.iterdir()) == sorted(LOG_NAMES)


def test_legacy_size_overrides_both_schedules(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, legacy_size=True)
    output = _debug(fixture)
    assert "'size' overrides previously specified 'daily'" in output
    assert "'size' overrides previously specified 'weekly'" in output
    assert output.count("log size is below the 'size' threshold") == 3
    assert "log needs rotating" not in output
    _assert_untouched(fixture)


def test_maxsize_honors_due_schedules_without_rotating(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = _debug(fixture)
    assert "'size' overrides" not in output
    assert "after 1 days (7 rotations)" in output
    assert "weekly (4 rotations)" in output
    assert output.count("log needs rotating") == 3
    assert "5368709120 are rotated earlier" in output
    _assert_untouched(fixture)


def test_malformed_config_is_not_a_success_receipt(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = fixture.config.read_text(encoding="utf-8")
    fixture.config.write_text(source.replace("\trotate 7\n", "\trotate invalid\n"), encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="did not parse both fixture groups"):
        _debug(fixture)
    _assert_untouched(fixture)


def test_policy_preserves_log_scope_and_retention_counts() -> None:
    source = POLICY.read_text(encoding="utf-8")
    assert source == PREIMAGE.read_text(encoding="utf-8").replace("\tsize 5G\n", "\tmaxsize 5G\n")
    paths = [line for line in source.splitlines() if line.startswith("/var/log/")]
    assert paths == [
        "/var/log/syslog", "/var/log/mail.info", "/var/log/mail.warn", "/var/log/mail.err",
        "/var/log/mail.log", "/var/log/daemon.log", "/var/log/kern.log", "/var/log/auth.log",
        "/var/log/user.log", "/var/log/lpr.log", "/var/log/cron.log", "/var/log/debug",
        "/var/log/messages",
    ]
    assert source.count("\tmaxsize 5G\n") == 2
    assert "\tsize " not in source
    assert source.count("\trotate 7\n") == 1
    assert source.count("\trotate 4\n") == 1
    assert source.count("\tdelaycompress\n") == 2
    assert source.count("\tcompress\n") == 2
    assert source.count("/usr/lib/rsyslog/rsyslog-rotate") == 2
