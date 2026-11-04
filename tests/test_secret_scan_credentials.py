from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "secret_scan_guard.py"
AUTH = """instances:
  - url: https://dashboard.gitguardian.com
    accounts:
      - workspace_id: 1
        token: not-a-key
        type: personal_access_token
        token_name: fixture
        expire_at: null
"""


@dataclass(frozen=True, slots=True)
class CredentialCase:
    env_key: str | None = None
    auth_yaml: str | None = None
    dotenv: str | None = None
    missing_dotenv: bool = False
    scan_exit: int = 3


def _run_case(
    tmp_path: Path, case: CredentialCase
) -> tuple[subprocess.CompletedProcess[str], bool]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    if case.auth_yaml is not None:
        _ = (config_dir / "auth_config.yaml").write_text(case.auth_yaml, encoding="utf-8")
    if case.dotenv is not None:
        _ = (tmp_path / ".env").write_text(case.dotenv, encoding="utf-8")
    marker = tmp_path / "called"
    fake = tmp_path / "scanner.py"
    _ = fake.write_text(
        """import os
from pathlib import Path
Path(os.environ['FAKE_SCANNER_MARKER']).write_text('called')
raise SystemExit(int(os.environ['FAKE_SCANNER_EXIT']))
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    for key in (
        "GITGUARDIAN_API_KEY",
        "GITGUARDIAN_API_URL",
        "GITGUARDIAN_DOTENV_PATH",
    ):
        _ = env.pop(key, None)
    env.update(
        GG_CONFIG_DIR=str(config_dir),
        GG_USER_HOME_DIR=str(tmp_path / "home"),
        GG_CACHE_DIR=str(tmp_path / "cache"),
        GGSHIELD_EXECUTABLE=sys.executable,
        GGSHIELD_EXECUTABLE_PREFIX=str(fake),
        GGSHIELD_NO_KEYRING="1",
        GITGUARDIAN_INSTANCE="https://dashboard.gitguardian.com",
        GITGUARDIAN_DONT_LOAD_ENV="0",
        FAKE_SCANNER_MARKER=str(marker),
        FAKE_SCANNER_EXIT=str(case.scan_exit),
    )
    if case.env_key is not None:
        env["GITGUARDIAN_API_KEY"] = case.env_key
    if case.missing_dotenv:
        env["GITGUARDIAN_DOTENV_PATH"] = str(tmp_path / "absent.env")
    result = subprocess.run(
        ["uv", "run", "--python", "3.12", "--script", str(SCRIPT), "pre-commit"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, marker.exists()


@pytest.mark.parametrize("key", [None, ""])
def test_absent_credentials_skip_with_notice(tmp_path: Path, key: str | None) -> None:
    result, called = _run_case(tmp_path, CredentialCase(env_key=key))
    assert result.returncode == 0
    assert "API key not configured" in result.stderr
    assert "Gitleaks is the required gate" in result.stderr
    assert not called


@pytest.mark.parametrize("exit_code", [2, 3])
def test_configured_environment_key_rejection_blocks(tmp_path: Path, exit_code: int) -> None:
    result, called = _run_case(
        tmp_path, CredentialCase(env_key="not-a-key", scan_exit=exit_code)
    )
    assert result.returncode == exit_code
    assert called


def test_configured_saved_account_rejection_blocks(tmp_path: Path) -> None:
    result, called = _run_case(tmp_path, CredentialCase(auth_yaml=AUTH))
    assert result.returncode == 3
    assert called


def test_expired_saved_account_is_not_absence(tmp_path: Path) -> None:
    expired = AUTH.replace("expire_at: null", 'expire_at: "2000-01-01T00:00:00+00:00"')
    result, called = _run_case(tmp_path, CredentialCase(auth_yaml=expired))
    assert result.returncode == 3
    assert called


def test_unavailable_keyring_account_is_not_absence(tmp_path: Path) -> None:
    keyring_auth = AUTH.replace("token: not-a-key", "token: __KEYRING__")
    result, called = _run_case(tmp_path, CredentialCase(auth_yaml=keyring_auth))
    assert result.returncode == 3
    assert called


def test_dotenv_key_is_configured_and_rejection_blocks(tmp_path: Path) -> None:
    result, called = _run_case(tmp_path, CredentialCase(dotenv="GITGUARDIAN_API_KEY=not-a-key\n"))
    assert result.returncode == 3
    assert called


def test_malformed_auth_config_is_not_absence(tmp_path: Path) -> None:
    result, called = _run_case(
        tmp_path, CredentialCase(auth_yaml="instances: [do-not-echo-fixture\n")
    )
    assert result.returncode != 0
    assert "configuration could not be loaded" in result.stderr
    assert "do-not-echo-fixture" not in result.stderr
    assert not called


def test_missing_explicit_dotenv_is_not_absence(tmp_path: Path) -> None:
    result, called = _run_case(tmp_path, CredentialCase(missing_dotenv=True))
    assert result.returncode != 0
    assert "GITGUARDIAN_DOTENV_PATH" in result.stderr
    assert not called


def test_dotenv_cannot_turn_configured_key_into_absence(tmp_path: Path) -> None:
    result, called = _run_case(
        tmp_path, CredentialCase(env_key="not-a-key", dotenv="GITGUARDIAN_API_KEY=\n")
    )
    assert result.returncode == 3
    assert called


def test_empty_environment_does_not_hide_saved_account(tmp_path: Path) -> None:
    result, called = _run_case(tmp_path, CredentialCase(env_key="", auth_yaml=AUTH))
    assert result.returncode == 3
    assert called


def test_configured_clean_scan_is_not_skipped(tmp_path: Path) -> None:
    result, called = _run_case(tmp_path, CredentialCase(env_key="not-a-key", scan_exit=0))
    assert result.returncode == 0
    assert called
    assert "not configured" not in result.stderr
