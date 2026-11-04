from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

SCRIPT = Path(__file__).parents[1] / "scripts" / "secret_scan_guard.py"
QUOTA_MESSAGE = "no more API calls available"
INVOCATION = TypeAdapter(tuple[str, ...])


@dataclass(frozen=True, slots=True)
class GuardResult:
    returncode: int
    stdout: str
    stderr: str
    invocations: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class FakeBehavior:
    scan_exit: int
    scan_stderr: str = ""
    scan_stdout: str = ""
    quota_exit: int = 0
    quota_stdout: str = '{"count": 10000, "limit": 10000, "remaining": 0}'
    scan_delay_seconds: float = 0
    quota_delay_seconds: float = 0
    command_timeout_seconds: float = 60


def _write_fake_ggshield(tmp_path: Path) -> Path:
    fake = tmp_path / "fake_ggshield.py"
    _ = fake.write_text(
        """from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Event

log_path = Path(os.environ["FAKE_GGSHIELD_LOG"])
with log_path.open("a", encoding="utf-8", newline="\\n") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")

if sys.argv[1:] == ["quota", "--json"]:
    Event().wait(float(os.environ["FAKE_QUOTA_DELAY_SECONDS"]))
    print(os.environ["FAKE_QUOTA_STDOUT"])
    print(os.environ.get("FAKE_QUOTA_STDERR", ""), file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_QUOTA_EXIT", "0")))

Event().wait(float(os.environ["FAKE_SCAN_DELAY_SECONDS"]))
print(os.environ.get("FAKE_SCAN_STDOUT", ""))
print(os.environ.get("FAKE_SCAN_STDERR", ""), file=sys.stderr)
raise SystemExit(int(os.environ.get("FAKE_SCAN_EXIT", "0")))
""",
        encoding="utf-8",
        newline="\n",
    )
    return fake


def _run_guard(
    tmp_path: Path,
    behavior: FakeBehavior,
) -> GuardResult:
    fake = _write_fake_ggshield(tmp_path)
    log_path = tmp_path / "invocations.jsonl"
    environment = os.environ.copy()
    environment.update(
        {
            "FAKE_GGSHIELD_LOG": str(log_path),
            "FAKE_QUOTA_EXIT": str(behavior.quota_exit),
            "FAKE_QUOTA_STDOUT": behavior.quota_stdout,
            "FAKE_SCAN_EXIT": str(behavior.scan_exit),
            "FAKE_SCAN_STDERR": behavior.scan_stderr,
            "FAKE_SCAN_STDOUT": behavior.scan_stdout,
            "FAKE_SCAN_DELAY_SECONDS": str(behavior.scan_delay_seconds),
            "FAKE_QUOTA_DELAY_SECONDS": str(behavior.quota_delay_seconds),
            "GGSHIELD_COMMAND_TIMEOUT_SECONDS": str(behavior.command_timeout_seconds),
            "GGSHIELD_EXECUTABLE": sys.executable,
            "GGSHIELD_EXECUTABLE_PREFIX": str(fake),
            "GITGUARDIAN_API_KEY": "not-a-key",
            "GITGUARDIAN_INSTANCE": "https://dashboard.gitguardian.com",
            "GITGUARDIAN_DONT_LOAD_ENV": "1",
            "GG_CONFIG_DIR": str(tmp_path / "config"),
            "GG_USER_HOME_DIR": str(tmp_path / "home"),
        }
    )

    completed = subprocess.run(
        ["uv", "run", "--python", "3.12", "--script", str(SCRIPT), "pre-commit"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=120,
    )
    invocations = (
        tuple(
            INVOCATION.validate_json(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        )
        if log_path.exists()
        else ()
    )
    return GuardResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        invocations=invocations,
    )


def test_returns_success_when_scan_is_clean(tmp_path: Path) -> None:
    # Given: a clean GitGuardian scan.
    # When: the pre-commit guard runs.
    result = _run_guard(tmp_path, FakeBehavior(scan_exit=0, scan_stdout="clean scan"))

    # Then: the clean result is preserved without a quota lookup.
    assert result.returncode == 0
    assert "clean scan" in result.stdout
    assert result.invocations == (("secret", "scan", "pre-commit"),)


def test_returns_finding_when_scan_detects_secret(tmp_path: Path) -> None:
    # Given: a blocking secret finding.
    # When: the pre-commit guard runs.
    result = _run_guard(tmp_path, FakeBehavior(scan_exit=1, scan_stderr="policy break"))

    # Then: the finding remains blocking and no quota lookup hides it.
    assert result.returncode == 1
    assert "policy break" in result.stderr
    assert result.invocations == (("secret", "scan", "pre-commit"),)


def test_returns_success_when_quota_exhaustion_is_confirmed(tmp_path: Path) -> None:
    # Given: ggshield reports its quota error and the quota endpoint confirms zero remaining calls.
    # When: the pre-commit guard runs.
    result = _run_guard(
        tmp_path,
        FakeBehavior(scan_exit=128, scan_stderr=QUOTA_MESSAGE),
    )

    # Then: only that confirmed service limitation becomes non-blocking.
    assert result.returncode == 0
    assert "confirmed exhausted quota" in result.stderr
    assert result.invocations == (
        ("secret", "scan", "pre-commit"),
        ("quota", "--json"),
    )


@pytest.mark.parametrize(
    ("scan_stderr", "quota_exit", "quota_stdout"),
    [
        ("authentication failed", 0, '{"remaining": 0}'),
        (QUOTA_MESSAGE, 0, '{"remaining": 1}'),
        (QUOTA_MESSAGE, 1, ""),
        (QUOTA_MESSAGE, 0, "not-json"),
    ],
)
def test_returns_original_failure_when_quota_is_not_confirmed(
    tmp_path: Path,
    scan_stderr: str,
    quota_exit: int,
    quota_stdout: str,
) -> None:
    # Given: an exit 128 that is not a fully confirmed exhausted-quota condition.
    # When: the pre-commit guard runs.
    result = _run_guard(
        tmp_path,
        FakeBehavior(
            scan_exit=128,
            scan_stderr=scan_stderr,
            quota_exit=quota_exit,
            quota_stdout=quota_stdout,
        ),
    )

    # Then: the original failure remains blocking.
    assert result.returncode == 128
    assert scan_stderr in result.stderr
    expected: tuple[tuple[str, ...], ...] = (("secret", "scan", "pre-commit"),)
    if scan_stderr == QUOTA_MESSAGE:
        expected += (("quota", "--json"),)
    assert result.invocations == expected


def test_help_describes_ci_and_pre_commit_modes() -> None:
    # Given: the installed script surface.
    # When: an operator requests help.
    completed = subprocess.run(
        ["uv", "run", "--python", "3.12", "--script", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Then: both supported execution modes are discoverable.
    assert completed.returncode == 0
    assert "pre-commit" in completed.stdout
    assert "ci" in completed.stdout


def test_scan_timeout_blocks_without_quota_bypass(tmp_path: Path) -> None:
    behavior = FakeBehavior(scan_exit=0, scan_delay_seconds=3, command_timeout_seconds=1)
    result = _run_guard(tmp_path, behavior)
    assert result.returncode == 124
    assert "scan timed out" in result.stderr
    assert result.invocations == (("secret", "scan", "pre-commit"),)


def test_quota_timeout_preserves_original_scan_failure(tmp_path: Path) -> None:
    behavior = FakeBehavior(
        scan_exit=128,
        scan_stderr=QUOTA_MESSAGE,
        quota_delay_seconds=3,
        command_timeout_seconds=1,
    )
    result = _run_guard(tmp_path, behavior)
    assert result.returncode == 128
    assert "quota lookup timed out" in result.stderr
    assert "not independently confirmed" in result.stderr


@pytest.mark.parametrize("timeout_seconds", [0, -1, float("nan")])
def test_invalid_timeout_never_starts_scanner(
    tmp_path: Path, timeout_seconds: float
) -> None:
    result = _run_guard(
        tmp_path, FakeBehavior(scan_exit=0, command_timeout_seconds=timeout_seconds)
    )
    assert result.returncode != 0
    assert "command_timeout_seconds" in result.stderr
    assert result.invocations == ()


@pytest.mark.parametrize("exit_code", [1, 3])
def test_quota_message_with_other_exit_remains_blocking(
    tmp_path: Path, exit_code: int
) -> None:
    result = _run_guard(
        tmp_path, FakeBehavior(scan_exit=exit_code, scan_stderr=QUOTA_MESSAGE)
    )
    assert result.returncode == exit_code
    assert result.invocations == (("secret", "scan", "pre-commit"),)


def test_missing_scanner_executable_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GGSHIELD_EXECUTABLE", str(tmp_path / "not-installed"))
    monkeypatch.setenv("GITGUARDIAN_API_KEY", "not-a-key")
    monkeypatch.setenv("GITGUARDIAN_DONT_LOAD_ENV", "1")
    monkeypatch.setenv("GG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("GG_USER_HOME_DIR", str(tmp_path / "home"))
    result = subprocess.run(
        ["uv", "run", "--python", "3.12", "--script", str(SCRIPT), "pre-commit"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 127
    assert "executable not found" in result.stderr
