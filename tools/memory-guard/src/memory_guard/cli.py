"""CLI: `check` runs one guard pass, `sample` prints the current readings. JSON on stdout, diagnostics on stderr."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from memory_guard import __version__
from memory_guard.adapters.windows_probe import WindowsMemoryProbe
from memory_guard.composition import build_check
from memory_guard.config import Settings
from memory_guard.domain.errors import GuardError

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
err = Console(stderr=True)

EnvFile = Annotated[
    Path | None, typer.Option("--env-file", help="Env file with MEMORY_GUARD_* settings.", exists=True, dir_okay=False)
]


def _settings(env_file: Path | None, **overrides: object) -> Settings:
    try:
        base = Settings(_env_file=env_file) if env_file else Settings()  # type: ignore[call-arg]
        return Settings.model_validate({**base.model_dump(), **{k: v for k, v in overrides.items() if v is not None}})
    except ValidationError as exc:
        err.print(f"[red]configuration invalid[/red]: {exc}")
        raise typer.Exit(2) from exc


@app.command()
def check(
    env_file: EnvFile = None,
    min_free_virtual_gb: Annotated[float | None, typer.Option(help="Override, for forced-threshold tests.")] = None,
    min_free_ram_gb: Annotated[float | None, typer.Option(help="Override, for forced-threshold tests.")] = None,
    state_dir: Annotated[Path | None, typer.Option(help="Override, to keep a test apart from the real state.")] = None,
    reclaim_enabled: Annotated[bool | None, typer.Option(help="Override the WSL cache-drop kill switch.")] = None,
) -> None:
    """Sample memory, alert on sustained pressure, announce recovery. Exit 1 on any failure."""
    settings = _settings(
        env_file,
        min_free_virtual_gb=min_free_virtual_gb,
        min_free_ram_gb=min_free_ram_gb,
        state_dir=state_dir,
        reclaim_enabled=reclaim_enabled,
    )
    try:
        result = build_check(settings)()
    except GuardError as exc:
        err.print(f"[red]memory-guard check failed[/red]: {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
    s = result.sample
    row = {
        "free_virtual": s.free_virtual,
        "free_ram": s.free_ram,
        "nonpaged_pool": s.nonpaged_pool,
        "alerted": [c.value for c in result.alerted],
        "recovered": [c.value for c in result.recovered],
        "reclaim": result.reclaim.summary() if result.reclaim else None,
    }
    sys.stdout.write(json.dumps(row) + "\n")


@app.command()
def sample() -> None:
    """Print the current readings; sends nothing."""
    try:
        s = WindowsMemoryProbe().sample()
    except GuardError as exc:
        err.print(f"[red]memory-guard sample failed[/red]: {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
    row = {
        "commit_used": s.commit_used,
        "commit_limit": s.commit_limit,
        "free_ram": s.free_ram,
        "nonpaged_pool": s.nonpaged_pool,
    }
    sys.stdout.write(json.dumps(row) + "\n")


@app.command()
def version() -> None:
    sys.stdout.write(__version__ + "\n")
