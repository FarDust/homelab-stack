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


def _write_fake_ggshield(tmp_path: Path) -> Path:
    fake = tmp_path / "fake_ggshield.py"
    _ = fake.write_text(
        """from __future__ import annotations

import json
import os
import sys
from pathlib import Path

log_path = Path(os.environ["FAKE_GGSHIELD_LOG"])
with log_path.open("a", encoding="utf-8", newline="\\n") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")

if sys.argv[1:] == ["quota", "--json"]:
    print(os.environ["FAKE_QUOTA_STDOUT"])
    print(os.environ.get("FAKE_QUOTA_STDERR", ""), file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_QUOTA_EXIT", "0")))

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
            "GGSHIELD_EXECUTABLE": sys.executable,
            "GGSHIELD_EXECUTABLE_PREFIX": str(fake),
        }
    )

    completed = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "pre-commit"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
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


def test_help_describes_ci_and_pre_commit_modes() -> None:
    # Given: the installed script surface.
    # When: an operator requests help.
    completed = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    # Then: both supported execution modes are discoverable.
    assert completed.returncode == 0
    assert "pre-commit" in completed.stdout
    assert "ci" in completed.stdout
