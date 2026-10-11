from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, TypeAdapter

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "pre-commit.yml"
NOTICE = "::notice::GitGuardian API key not configured; Gitleaks is the required gate"


class Step(BaseModel):
    name: str
    run: str | None = None


def _run_api_step(
    tmp_path: Path, key: str | None
) -> tuple[subprocess.CompletedProcess[str], bool]:
    steps = TypeAdapter(list[Step]).validate_python(
        yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["pre-commit"]["steps"]
    )
    matches = [step for step in steps if step.name.startswith("GitGuardian ")]
    assert len(matches) == 1
    script = matches[0].run
    assert script is not None
    marker = tmp_path / "invoked"
    fake_uv = tmp_path / "uv"
    _ = fake_uv.write_text(
        f"""#!{sys.executable}
import os
import sys
from pathlib import Path

expected = ['run', '--python', '3.12', '--script', 'scripts/secret_scan_guard.py', 'ci']
if sys.argv[1:] != expected:
    raise SystemExit(99)
Path(os.environ['FAKE_UV_MARKER']).write_text('invoked')
print('Invalid GitGuardian API key.', file=sys.stderr)
raise SystemExit(3)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o700)
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path) + os.pathsep + environment["PATH"]
    environment["FAKE_UV_MARKER"] = str(marker)
    if key is None:
        _ = environment.pop("GITGUARDIAN_API_KEY", None)
    else:
        environment["GITGUARDIAN_API_KEY"] = key
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-c", script],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, marker.exists()


@pytest.mark.parametrize("key", [None, ""])
def test_missing_api_key_emits_notice_without_invoking_guard(
    tmp_path: Path, key: str | None
) -> None:
    result, invoked = _run_api_step(tmp_path, key)
    assert result.returncode == 0
    assert NOTICE in result.stdout
    assert not invoked


def test_rejected_configured_api_key_preserves_blocking_exit(tmp_path: Path) -> None:
    result, invoked = _run_api_step(tmp_path, "invalid-test-key")
    assert invoked
    assert result.returncode == 3
    assert "Invalid GitGuardian API key." in result.stderr
    assert NOTICE not in result.stdout
