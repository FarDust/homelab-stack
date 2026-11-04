"""Tests for scripts/env_contract.py, run through its CLI so the uv script header is exercised too."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[1]
SCRIPT = REPO / "scripts" / "env_contract.py"
SENTINEL = "s3ntinel-value-must-never-print"

STACK = """\
services:
  web:
    image: example/web:${WEB_TAG:-1.0}
    environment:
      DOMAIN: web.${LOCAL_DOMAIN}
      TOKEN: ${WEB_TOKEN?WEB_TOKEN is required}
      NESTED: ${OUTER:-${INNER:-fallback}}
      ESCAPED: $$NOT_A_VARIABLE
      BARE: $BARE_VAR
# commented ${COMMENTED_OUT}
"""


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd, check=False
    )


def variable(name: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": name,
        "kind": "literal",
        "owner": "main/web",
        "used_by": ["main/web"],
        "required": True,
        "description": f"{name} for tests",
        "example": f"example_{name.lower()}",
    }
    base.update(overrides)
    return base


def good_variables() -> list[dict[str, object]]:
    return [
        variable("BARE_VAR"),
        variable("INNER", required=False, default="fallback"),
        variable("LOCAL_DOMAIN"),
        variable("OUTER", required=False, default="", example=""),
        variable(
            "WEB_TOKEN",
            kind="secret-file",
            secret_file="web/token",
            example=None,
        ),
        variable("WEB_TAG", required=False, default="1.0"),
    ]


def write_repo(root: Path, variables: list[dict[str, object]] | None = None, generate: bool = True) -> Path:
    (root / "stacks" / "main").mkdir(parents=True)
    (root / "stacks" / "main" / "web.yml").write_text(STACK, encoding="utf-8")
    (root / "config").mkdir()
    doc = {"version": 1, "variables": variables if variables is not None else good_variables()}
    (root / "config" / "env-contract.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    (root / ".env.example").write_text("", encoding="utf-8")
    if generate:
        result = run("generate-example", "--root", str(root))
        assert result.returncode == 0, result.stderr
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return write_repo(tmp_path)


def test_scan_reports_interpolations_defaults_and_requirements(repo: Path) -> None:
    result = run("scan", "--json", "--root", str(repo))
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert set(found) == {"BARE_VAR", "INNER", "LOCAL_DOMAIN", "OUTER", "WEB_TAG", "WEB_TOKEN"}
    assert found["WEB_TOKEN"]["required"] is True
    assert found["WEB_TAG"]["defaults"] == ["1.0"]
    assert found["OUTER"]["defaults"] == ["${INNER:-fallback}"]
    assert found["LOCAL_DOMAIN"]["bare"] is True
    assert "NOT_A_VARIABLE" not in found and "COMMENTED_OUT" not in found


def test_check_passes_on_a_consistent_repository(repo: Path) -> None:
    result = run("check", "--root", str(repo))
    assert result.returncode == 0, result.stderr
    assert "passed" in result.stdout


def test_check_reports_a_used_variable_missing_from_the_contract(tmp_path: Path) -> None:
    variables = [v for v in good_variables() if v["name"] != "LOCAL_DOMAIN"]
    repo = write_repo(tmp_path, variables)
    result = run("check", "--root", str(repo))
    assert result.returncode == 1
    assert "LOCAL_DOMAIN: used by main/web but missing from the contract" in result.stderr


def test_check_reports_a_contract_variable_no_stack_uses(tmp_path: Path) -> None:
    repo = write_repo(tmp_path, [*good_variables(), variable("GHOST")])
    result = run("check", "--root", str(repo))
    assert result.returncode == 1
    assert "GHOST: listed in the contract but no stack uses it" in result.stderr


def test_external_consumers_exempt_a_variable_from_the_unused_rule(tmp_path: Path) -> None:
    ghost = variable("GHOST", used_by=[], owner="external", external_consumers=["cluster-utils"])
    repo = write_repo(tmp_path, [*good_variables(), ghost])
    result = run("check", "--root", str(repo))
    assert result.returncode == 0, result.stderr


def test_check_reports_a_shared_variable_whose_used_by_differs_from_the_scan(tmp_path: Path) -> None:
    variables = good_variables()
    variables[2] = variable("LOCAL_DOMAIN", used_by=["main/other", "main/web"])
    repo = write_repo(tmp_path, variables)
    result = run("check", "--root", str(repo))
    assert result.returncode == 1
    assert "LOCAL_DOMAIN: used_by differs from the scan" in result.stderr


def test_check_reports_a_stack_required_variable_not_marked_required(tmp_path: Path) -> None:
    variables = good_variables()
    variables[4] = variable("WEB_TOKEN", kind="secret-file", secret_file="web/token", example=None, required=False, default="")
    repo = write_repo(tmp_path, variables)
    result = run("check", "--root", str(repo))
    assert result.returncode == 1
    assert "WEB_TOKEN: a stack requires it" in result.stderr


def test_check_reports_a_contract_variable_missing_from_the_example(repo: Path) -> None:
    example = repo / ".env.example"
    example.write_text(
        "\n".join(line for line in example.read_text().splitlines() if "LOCAL_DOMAIN" not in line) + "\n"
    )
    result = run("check", "--root", str(repo))
    assert result.returncode == 1
    assert "LOCAL_DOMAIN: missing from .env.example" in result.stderr


def test_generate_example_is_deterministic_and_never_writes_secret_values(repo: Path) -> None:
    first = (repo / ".env.example").read_text()
    assert run("generate-example", "--root", str(repo)).returncode == 0
    assert (repo / ".env.example").read_text() == first
    assert "export WEB_TOKEN=$(cat secrets/web/token | tr -d '\\n')" in first
    assert "export OUTER=" in first


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ([variable("A", required=True, default="x")], "cannot carry a default"),
        ([variable("A", required=False)], "needs an explicit default"),
        ([variable("A", kind="secret-file", example=None)], "needs secret_file"),
        ([variable("A", kind="secret-file", secret_file="a/b", required=False, default="hunter2", example=None)], "only default to the empty string"),
        ([variable("A", kind="secret-file", secret_file="a/b")], "holds no example value"),
        ([variable("A", owner="main/zzz")], "owner"),
        ([variable("A"), variable("A")], "duplicate variables"),
        ([variable("A", used_by=[])], "needs used_by stacks or external_consumers"),
        ([variable("A", surprise=True)], "Extra inputs are not permitted"),
    ],
)
def test_malformed_contract_is_rejected_with_a_diagnostic(tmp_path: Path, variables: list[dict[str, object]], message: str) -> None:
    repo = write_repo(tmp_path, variables, generate=False)
    result = run("check", "--root", str(repo))
    assert result.returncode == 2
    assert message in result.stderr


def test_unparseable_contract_yaml_is_rejected(tmp_path: Path) -> None:
    repo = write_repo(tmp_path, generate=False)
    (repo / "config" / "env-contract.yaml").write_text("version: [1\n", encoding="utf-8")
    result = run("check", "--root", str(repo))
    assert result.returncode == 2
    assert "not valid YAML" in result.stderr


def test_unterminated_interpolation_in_a_stack_is_an_explicit_failure(repo: Path) -> None:
    (repo / "stacks" / "main" / "web.yml").write_text("services:\n  a:\n    image: ${BROKEN:-x\n", encoding="utf-8")
    result = run("scan", "--root", str(repo))
    assert result.returncode == 2
    assert "unterminated" in result.stderr


def write_live(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def full_live(path: Path) -> Path:
    return write_live(
        path,
        f"export BARE_VAR={SENTINEL}",
        "export LOCAL_DOMAIN=example.test",
        f"export WEB_TOKEN=$(cat secrets/web/token | tr -d '\\n')  # {SENTINEL}",
    )


def test_check_live_accepts_a_matching_env_without_printing_values(repo: Path, tmp_path: Path) -> None:
    live = full_live(tmp_path / "live.env")
    result = run("check-live", str(live), "--root", str(repo))
    assert result.returncode == 0, result.stderr
    assert SENTINEL not in result.stdout + result.stderr


def test_check_live_reports_name_problems_and_still_prints_no_values(repo: Path, tmp_path: Path) -> None:
    live = write_live(
        tmp_path / "live.env",
        f"export BARE_VAR=$(echo {SENTINEL})",
        f"export STRAY={SENTINEL}",
        f"WEB_TOKEN={SENTINEL}",
    )
    result = run("check-live", str(live), "--root", str(repo), "--verbose")
    assert result.returncode == 1
    assert "STRAY: defined in the live env but missing from the contract" in result.stderr
    assert "LOCAL_DOMAIN: required in the contract but not defined" in result.stderr
    assert "BARE_VAR: contract kind literal but the live env defines it as computed" in result.stderr
    assert "WEB_TOKEN: contract kind secret-file but the live env defines it as literal" in result.stderr
    assert "WEB_TOKEN: contract exported=True but the live env defines it without `export`" in result.stderr
    assert SENTINEL not in result.stdout + result.stderr


def test_check_live_flags_missing_live_file_explicitly(repo: Path, tmp_path: Path) -> None:
    result = run("check-live", str(tmp_path / "absent.env"), "--root", str(repo))
    assert result.returncode == 2
    assert "cannot read live env" in result.stderr


def test_the_repository_contract_matches_its_stacks_and_example() -> None:
    result = run("check", "--root", str(REPO))
    assert result.returncode == 0, result.stderr
