#!/usr/bin/env -S uv run --python 3.12 --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "click>=8.1,<9",
#     "ggshield==1.55.0",
#     "marshmallow>=3.13,<5",
#     "pydantic>=2.12,<3",
#     "pydantic-settings>=2.12,<3",
#     "rich>=13.9,<14",
#     "typer>=0.20,<1",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv or pip install needed):
#      uv run --python 3.12 --script scripts/secret_scan_guard.py pre-commit
#      uv run --python 3.12 --script scripts/secret_scan_guard.py ci
# 3. Or make executable and run:
#      chmod +x scripts/secret_scan_guard.py && ./scripts/secret_scan_guard.py ci
# ──────────────────

"""Run optional ggshield without weakening the separate Gitleaks gate."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Final, assert_never

import typer
from click import ClickException
from ggshield.core.config import Config
from ggshield.core.env_utils import load_dot_env
from ggshield.core.errors import UnknownInstanceError
from ggshield.utils.os import getenv_bool
from marshmallow import ValidationError as GGConfigValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console

QUOTA_ERROR: Final = "no more api calls available"
GGSHIELD_SHARED_ERROR_EXIT: Final = 128
COMMAND_NOT_FOUND_EXIT: Final = 127
COMMAND_TIMEOUT_EXIT: Final = 124
CONFIGURATION_ERROR_EXIT: Final = 2


class ScanMode(StrEnum):
    """Supported ggshield scan surfaces."""

    PRE_COMMIT = "pre-commit"
    CI = "ci"


class Settings(BaseSettings):
    """Resolve the ggshield executable without embedding environment details."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GGSHIELD_",
        extra="ignore",
        frozen=True,
    )

    executable: str = "ggshield"
    executable_prefix: Path | None = None
    command_timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)


class QuotaStatus(BaseModel):
    """Parse the minimum trusted shape returned by ``ggshield quota --json``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore",
        frozen=True,
        strict=True,
    )

    remaining: int


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Retain external command output and its exact exit status."""

    returncode: int
    stdout: str
    stderr: str


def _command(settings: Settings, arguments: tuple[str, ...]) -> list[str]:
    prefix = (
        [str(settings.executable_prefix)]
        if settings.executable_prefix is not None
        else []
    )
    return [settings.executable, *prefix, *arguments]


def _run(settings: Settings, arguments: tuple[str, ...]) -> CommandResult:
    completed = subprocess.run(
        _command(settings, arguments),
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=settings.command_timeout_seconds,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _scan_arguments(mode: ScanMode) -> tuple[str, ...]:
    match mode:
        case ScanMode.PRE_COMMIT:
            return ("secret", "scan", "pre-commit")
        case ScanMode.CI:
            return ("secret", "scan", "ci")
        case unreachable:
            assert_never(unreachable)


def _replay(result: CommandResult) -> None:
    _ = sys.stdout.write(result.stdout)
    _ = sys.stderr.write(result.stderr)


def _quota_is_exhausted(settings: Settings) -> bool:
    quota_result = _run(settings, ("quota", "--json"))
    if quota_result.returncode != 0:
        return False
    try:
        quota = QuotaStatus.model_validate_json(quota_result.stdout)
    except ValidationError:
        return False
    return quota.remaining == 0


def main(
    mode: Annotated[
        ScanMode,
        typer.Argument(
            help="Use pre-commit for staged changes or ci for the CI checkout."
        ),
    ],
) -> None:
    """Run configured ggshield; Gitleaks remains a required separate gate."""
    settings = Settings()
    had_environment_key = bool(os.environ.get("GITGUARDIAN_API_KEY"))
    try:
        dotenv_path = os.environ.get("GITGUARDIAN_DOTENV_PATH")
        if (
            not getenv_bool("GITGUARDIAN_DONT_LOAD_ENV")
            and dotenv_path
            and not Path(dotenv_path).is_file()
        ):
            Console(stderr=True).print(
                "[red]GITGUARDIAN_DOTENV_PATH must reference an existing file.[/red]"
            )
            raise typer.Exit(CONFIGURATION_ERROR_EXIT)
        _ = load_dot_env()
        config = Config()
        try:
            instance = config.auth_config.get_instance(config.instance_name)
        except UnknownInstanceError:
            has_saved_account = False
        else:
            has_saved_account = instance.account is not None
    except (ClickException, GGConfigValidationError, OSError, ValueError) as exc:
        Console(stderr=True).print(
            f"[red]GitGuardian configuration could not be loaded ({type(exc).__name__}); scan blocked.[/red]"
        )
        raise typer.Exit(CONFIGURATION_ERROR_EXIT) from exc
    if (
        not had_environment_key
        and not os.environ.get("GITGUARDIAN_API_KEY")
        and not has_saved_account
    ):
        Console(stderr=True).print(
            "[yellow]GitGuardian API key not configured; Gitleaks is the required gate.[/yellow]"
        )
        raise typer.Exit(0)
    os.environ["GITGUARDIAN_DONT_LOAD_ENV"] = "1"
    try:
        scan_result = _run(settings, _scan_arguments(mode))
    except FileNotFoundError:
        Console(stderr=True).print(
            f"[red]ggshield executable not found:[/red] {settings.executable}"
        )
        raise typer.Exit(COMMAND_NOT_FOUND_EXIT) from None
    except subprocess.TimeoutExpired as exc:
        Console(stderr=True).print(
            f"[red]ggshield scan timed out after {exc.timeout} seconds; scan failed.[/red]"
        )
        raise typer.Exit(COMMAND_TIMEOUT_EXIT) from exc

    _replay(scan_result)
    quota_candidate = (
        scan_result.returncode == GGSHIELD_SHARED_ERROR_EXIT
        and QUOTA_ERROR in f"{scan_result.stdout}\n{scan_result.stderr}".lower()
    )
    if not quota_candidate:
        if scan_result.returncode != 0:
            Console(stderr=True).print(
                f"[red]ggshield scan failed with exit {scan_result.returncode}; quota bypass does not apply.[/red]"
            )
        raise typer.Exit(scan_result.returncode)

    try:
        exhausted = _quota_is_exhausted(settings)
    except FileNotFoundError:
        exhausted = False
    except subprocess.TimeoutExpired as exc:
        Console(stderr=True).print(
            f"[red]ggshield quota lookup timed out after {exc.timeout} seconds.[/red]"
        )
        exhausted = False
    if not exhausted:
        Console(stderr=True).print(
            "[red]ggshield quota exhaustion was not independently confirmed; preserving exit 128.[/red]"
        )
        raise typer.Exit(scan_result.returncode)

    Console(stderr=True).print(
        "[yellow]ggshield has confirmed exhausted quota; the API scan is non-blocking for this run. Gitleaks remains a required separate gate.[/yellow]"
    )


if __name__ == "__main__":
    app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
    app.command()(main)
    app()
