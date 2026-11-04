"""scan-tree: the generic private-indicator rules over the whole tracked tree. As decided in docs/adr/private_indicator_guard_adr.md."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_private_indicators.py"
# Built at runtime so this file carries no indicator itself.
TAILNET_ADDRESS = "100." + "100.1.5"
TAILNET_NAME = "node." + "bobcat-dragon.ts" + ".net"
PRIVATE_DOMAIN = "private-deployment" + ".example"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "scan-tree", *args],
        cwd=repo, capture_output=True, text=True, check=False,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def track(repo: Path, name: str, content: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)


def test_clean_tree_passes(repo: Path) -> None:
    track(repo, "docs/a.md", "Use https://grafana.example.com and 100.100.100.100 and 100.64.0.10.\n")
    assert run(repo).returncode == 0


@pytest.mark.parametrize("content,label", [
    (f"address {TAILNET_ADDRESS}\n", "tailnet-address"),
    (f"host {TAILNET_NAME}\n", "tailnet-name"),
    ("bucket project-" + "123456789012\n", "bucket-with-numeric-project-id"),
])
def test_generic_rules_flag_tracked_files_without_printing_values(repo: Path, content: str, label: str) -> None:
    track(repo, "docs/a.md", content)
    done = run(repo)
    assert done.returncode == 1
    assert label in done.stderr.replace("\n", "")
    assert "123456789012" not in done.stderr and TAILNET_ADDRESS not in done.stderr


def test_forbidden_paths_are_flagged(repo: Path) -> None:
    track(repo, "reports/x.md", "text\n")
    done = run(repo)
    assert done.returncode == 1 and "path rule" in done.stderr


def test_deny_list_is_optional_and_applies_when_given(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    track(repo, "docs/a.md", f"see {PRIVATE_DOMAIN}\n")
    assert run(repo).returncode == 0
    deny = tmp_path_factory.mktemp("deny") / "deny.txt"
    deny.write_text("# comment\n" + PRIVATE_DOMAIN.replace(".", r"\.") + "\n", encoding="utf-8")
    done = run(repo, "--deny-list", str(deny))
    assert done.returncode == 1 and "deny-list rule #2" in done.stderr
    assert PRIVATE_DOMAIN not in done.stderr


def test_missing_deny_list_is_an_explicit_failure(repo: Path) -> None:
    done = run(repo, "--deny-list", str(repo / "absent.txt"))
    assert done.returncode == 2 and "not found" in done.stderr


def test_binary_files_are_skipped(repo: Path) -> None:
    (repo / "blob.bin").write_bytes(b"\xff\xfe" + TAILNET_ADDRESS.encode())
    subprocess.run(["git", "add", "blob.bin"], cwd=repo, check=True)
    assert run(repo).returncode == 0
