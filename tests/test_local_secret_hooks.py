from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, TypeAdapter

CONFIG = Path(__file__).parents[1] / ".pre-commit-config.yaml"


class Hook(BaseModel):
    id: str
    entry: str | None = None


class Repository(BaseModel):
    hooks: list[Hook]


def _run_gitleaks_hook(
    tmp_path: Path, version: str | None, version_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], tuple[str, ...]]:
    repos = TypeAdapter(list[Repository]).validate_python(
        yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["repos"]
    )
    hooks = [hook for repo in repos for hook in repo.hooks if hook.id == "gitleaks"]
    assert len(hooks) == 1
    # The pinned upstream hook supplies this scan command when no entry is overridden.
    entry = hooks[0].entry or 'bash -c "gitleaks git --pre-commit --redact --staged --verbose"'
    command = shlex.split(entry)
    bash = shutil.which("bash")
    assert bash is not None
    assert command[0] == "bash"
    command[0] = bash
    marker = tmp_path / "scan.json"
    if version is not None:
        binary = tmp_path / "gitleaks"
        _ = binary.write_text(
            f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

if sys.argv[1:] == ['version']:
    print(os.environ['FAKE_GITLEAKS_VERSION'])
    raise SystemExit(int(os.environ['FAKE_GITLEAKS_VERSION_EXIT']))
Path(os.environ['FAKE_GITLEAKS_SCAN']).write_text(json.dumps(sys.argv[1:]))
""",
            encoding="utf-8",
        )
        binary.chmod(0o700)
    environment = os.environ.copy()
    environment.update(
        PATH=str(tmp_path),
        FAKE_GITLEAKS_VERSION=version or "",
        FAKE_GITLEAKS_VERSION_EXIT=str(version_exit),
        FAKE_GITLEAKS_SCAN=str(marker),
    )
    result = subprocess.run(
        command, env=environment, capture_output=True, text=True, check=False, timeout=10
    )
    arguments = (
        TypeAdapter(tuple[str, ...]).validate_json(marker.read_text(encoding="utf-8"))
        if marker.exists()
        else ()
    )
    return result, arguments


def test_pinned_gitleaks_runs_the_required_staged_scan(tmp_path: Path) -> None:
    result, arguments = _run_gitleaks_hook(tmp_path, "8.30.1")
    assert result.returncode == 0
    assert arguments[0] == "git"
    assert set(arguments[1:]) == {"--pre-commit", "--redact", "--staged", "--verbose"}


def test_other_gitleaks_version_blocks_before_scanning(tmp_path: Path) -> None:
    result, arguments = _run_gitleaks_hook(tmp_path, "8.29.0")
    assert result.returncode != 0
    assert "8.30.1" in result.stderr
    assert "8.29.0" in result.stderr
    assert arguments == ()


def test_missing_gitleaks_blocks(tmp_path: Path) -> None:
    result, arguments = _run_gitleaks_hook(tmp_path, None)
    assert result.returncode != 0
    assert arguments == ()


def test_failed_version_query_blocks_before_scanning(tmp_path: Path) -> None:
    result, arguments = _run_gitleaks_hook(tmp_path, "8.30.1", version_exit=17)
    assert result.returncode == 17
    assert arguments == ()
