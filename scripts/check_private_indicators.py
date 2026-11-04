#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "rich", "pydantic-settings"]
# ///
"""Pre-commit guard: reject staged changes that carry private deployment indicators.

The repository is public, so a commit must not contain identifiers that belong to the private deployment.
Three kinds of rules apply to the lines a commit ADDS (and to the paths it adds):

1. Built-in generic patterns (this file holds no real value): Tailscale CGNAT addresses and `*.ts.net` names, bucket
   names that embed a numeric project id, and consumer e-mail addresses.
2. A private deny-list, one literal or regular expression per line, read from `PRIVATE_INDICATORS_FILE`
   (default `.git/private-indicators.txt`, which Git never tracks). Matches are reported by rule number only, so the
   hook output does not leak the value either.
3. Path rules: reports, live env backups, agent state and generated output never belong in the repository.

As decided in docs/adr/private_indicator_guard_adr.md.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
from pathlib import Path

import typer
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console

app = typer.Typer(add_completion=False)
console = Console(stderr=True)

# Tailscale MagicDNS resolver is public knowledge and used in generic examples.
SELF = "scripts/check_private_indicators.py"
ALLOWED_ADDRESSES = {"100.100.100.100"}
CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Placeholder range used by the committed templates (for example clusters/main/k3s/k3s.env.template).
PLACEHOLDER_RANGE = ipaddress.ip_network("100.64.0.0/24")
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
GENERIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tailnet-name", re.compile(r"\b[\w-]+\.ts\.net\b")),
    ("bucket-with-numeric-project-id", re.compile(r"(?<![#\w-])[a-z][a-z0-9-]*-\d{9,}\b")),
    ("consumer-email", re.compile(r"\b[\w.+-]+@(?:gmail|googlemail|outlook|hotmail|yahoo|icloud|proton|protonmail)\.[a-z.]+\b", re.I)),
)
FORBIDDEN_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("reports", re.compile(r"^(?:docs/)?reports/")),
    ("live-env-backup", re.compile(r"(?:^|/)\.env\.bak")),
    ("timestamped-backup", re.compile(r"\.bak-")),
    ("agent-state", re.compile(r"^\.(?:omo|opencode|sisyphus|claude)/")),
    ("generated-graph-output", re.compile(r"(?:^|/)graphify-out/")),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRIVATE_INDICATORS_")

    file: Path = Path(".git/private-indicators.txt")


def git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def private_rules(path: Path) -> list[tuple[int, re.Pattern[str]]]:
    if not path.is_file():
        return []
    rules: list[tuple[int, re.Pattern[str]]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if text and not text.startswith("#"):
            rules.append((number, re.compile(text, re.I)))
    return rules


def scan_text(path: str, line_no: int, text: str, rules: list[tuple[int, re.Pattern[str]]]) -> list[str]:
    """Findings (values redacted) for one line of text."""
    findings: list[str] = []
    for label, pattern in GENERIC_PATTERNS:
        if pattern.search(text):
            findings.append(f"{path}:{line_no}: generic rule '{label}'")
    for match in IPV4.finditer(text):
        try:
            address = ipaddress.ip_address(match.group(1))
        except ValueError:
            continue
        if address in CGNAT and address not in PLACEHOLDER_RANGE and match.group(1) not in ALLOWED_ADDRESSES:
            findings.append(f"{path}:{line_no}: generic rule 'tailnet-address'")
    for number, pattern in rules:
        if pattern.search(text):
            findings.append(f"{path}:{line_no}: private deny-list rule #{number}")
    return findings


def path_findings(name: str) -> list[str]:
    return [f"{name}: path rule '{label}'" for label, pattern in FORBIDDEN_PATHS if pattern.search(name)]


def report(findings: list[str], scope: str) -> None:
    if not findings:
        return
    console.print(f"[bold red]Private indicators in {scope} (values are not printed):[/bold red]")
    for finding in sorted(set(findings)):
        console.print(f"  - {finding}")
    console.print(
        "Replace each value with an environment variable or a placeholder, or keep the file out of the repository "
        "(private sub-repository, ignored path)."
    )
    sys.exit(1)


def added_lines() -> list[tuple[str, int, str]]:
    """(path, line number, text) for every line the staged change adds."""
    out = git("diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR")
    found: list[tuple[str, int, str]] = []
    path, line_no = "", 0
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            found.append((path, line_no, line[1:]))
            line_no += 1
    return found


@app.command()
def pre_commit() -> None:
    """Check the staged change; exit 1 with redacted findings when something private would be committed."""
    settings = Settings()
    rules = private_rules(settings.file)
    findings: list[str] = []

    for name in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines():
        findings.extend(path_findings(name))

    for path, line_no, text in added_lines():
        if path == SELF:
            continue  # this file must name the ranges it looks for
        findings.extend(scan_text(path, line_no, text, rules))

    report(findings, "the staged change")


@app.command()
def scan_tree(
    deny_list: Path | None = typer.Option(None, "--deny-list", help="Optional private deny-list file (one regex per line)."),
) -> None:
    """Scan every tracked file with the generic rules (and the optional deny-list); exit 1 on findings.

    Intended for CI, where the private deny-list is absent: it enforces the generic subset over the whole tree.
    """
    if deny_list is not None and not deny_list.is_file():
        console.print(f"[bold red]Deny-list file not found:[/bold red] {deny_list}")
        sys.exit(2)
    rules = private_rules(deny_list) if deny_list is not None else []
    findings: list[str] = []
    for name in git("ls-files", "--cached").splitlines():
        if not name or name == SELF or not Path(name).is_file():
            continue
        findings.extend(path_findings(name))
        try:
            content = Path(name).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary file
        for line_no, text in enumerate(content.splitlines(), start=1):
            findings.extend(scan_text(name, line_no, text, rules))
    report(findings, "the tracked tree")


if __name__ == "__main__":
    app()
