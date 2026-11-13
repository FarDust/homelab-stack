"""Composition root and Typer commands of the break-glass CLI."""

from __future__ import annotations

import json
from pathlib import Path as FilePath
from typing import Annotated

import httpx
import typer
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console

from flags_breakglass.adapters import UnleashAdminApi, UnleashDatabase
from flags_breakglass.application import switch
from flags_breakglass.domain import BreakGlassError, FlagTarget

app = typer.Typer(help="Switch cluster feature flags when the admin panel is unavailable.", no_args_is_help=True)
err = Console(stderr=True)


class Settings(BaseSettings):
    """Runtime configuration; the token and DSN are read from files so they never enter argv or logs."""

    model_config = SettingsConfigDict(env_prefix="FLAGS_BREAKGLASS_")

    url: AnyHttpUrl
    token_file: FilePath
    dsn_file: FilePath | None = None
    project: str = "default"
    environment: str = "production"
    timeout_s: float = 15.0


def _settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as error:
        err.print(f"[red]configuration invalid:[/red] {error}")
        raise typer.Exit(2) from error


def _api(settings: Settings) -> UnleashAdminApi:
    token = settings.token_file.read_text().strip()
    client = httpx.Client(
        base_url=str(settings.url).rstrip("/"), headers={"Authorization": token}, timeout=settings.timeout_s
    )
    return UnleashAdminApi(client)


def _database(settings: Settings) -> UnleashDatabase | None:
    if settings.dsn_file is None:
        return None
    return UnleashDatabase(settings.dsn_file.read_text().strip())


def _switch(flag: str, enabled: bool) -> None:
    settings = _settings()
    try:
        target = FlagTarget(flag, settings.project, settings.environment)
        outcome = switch(target, enabled, _api(settings), _database(settings))
    except BreakGlassError as error:
        err.print(f"[red]failed:[/red] {error}")
        raise typer.Exit(1) from error
    state = "on" if outcome.enabled else "off"
    typer.echo(json.dumps({"flag": flag, "state": state, "path": outcome.path.value, "verified": outcome.verified}))
    err.print(f"[green]{flag} {state}[/green] via {outcome.path.value}: {outcome.note}")


@app.command()
def kill(flag: Annotated[str, typer.Argument(help="Flag key, e.g. trail.recording")]) -> None:
    """Switch a flag off (kill switch)."""
    _switch(flag, False)


@app.command()
def enable(flag: Annotated[str, typer.Argument(help="Flag key, e.g. trail.recording")]) -> None:
    """Switch a flag on in the environment (its strategies still decide who gets it)."""
    _switch(flag, True)


@app.command()
def export(out: Annotated[FilePath, typer.Option(help="File to write the snapshot JSON to")]) -> None:
    """Write every flag of the project with its strategies to a JSON file (import it in the admin panel)."""
    settings = _settings()
    try:
        snapshot = _api(settings).export(settings.project, settings.environment)
    except (BreakGlassError, httpx.HTTPError) as error:
        err.print(f"[red]export failed:[/red] {error!r}")
        raise typer.Exit(1) from error
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    features = snapshot.get("features", [])
    count = len(features) if isinstance(features, list) else 0
    typer.echo(json.dumps({"out": str(out), "features": count}))


if __name__ == "__main__":
    app()
