"""CLI: `publish` writes the files, `show` prints the snapshot without writing. JSON on stdout, diagnostics on stderr."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from open_prs_feed import __version__
from open_prs_feed.composition import build_collect, build_publish
from open_prs_feed.config import Settings
from open_prs_feed.domain.errors import FeedError
from open_prs_feed.domain.models import Snapshot

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
err = Console(stderr=True)

EnvFile = Annotated[
    Path | None, typer.Option("--env-file", help="Env file with OPEN_PRS_FEED_* settings.", exists=True, dir_okay=False)
]


def _settings(env_file: Path | None) -> Settings:
    try:
        return Settings(_env_file=env_file) if env_file else Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        err.print(f"[red]configuration invalid[/red]: {exc}")
        raise typer.Exit(2) from exc


def _table(snap: Snapshot) -> Table:
    t = Table(title=f"open PRs at {snap.generated_at.isoformat()}")
    for col in ("repo", "#", "head", "branch", "updated"):
        t.add_column(col)
    for pr in snap.prs:
        t.add_row(pr.repo, str(pr.number), pr.head_sha8, pr.branch, pr.updated_at.isoformat())
    return t


@app.command()
def publish(env_file: EnvFile = None) -> None:
    """Fetch every repository, then replace the detail file and the numbers file atomically."""
    settings = _settings(env_file)
    try:
        result = build_publish(settings)()
    except FeedError as exc:
        err.print(f"[red]open-prs-feed publish failed, previous files kept[/red]: {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
    err.print(_table(result.snapshot))
    err.print(f"wrote {result.detail_target} and {result.numbers_target}")
    sys.stdout.write(result.snapshot.render_numbers().decode("utf-8"))


@app.command()
def show(env_file: EnvFile = None) -> None:
    """Fetch every repository and print the detail JSON on stdout; writes nothing."""
    settings = _settings(env_file)
    try:
        snap = build_collect(settings)()
    except FeedError as exc:
        err.print(f"[red]open-prs-feed show failed[/red]: {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
    err.print(_table(snap))
    sys.stdout.write(snap.render_detail().decode("utf-8"))


@app.command()
def version() -> None:
    sys.stdout.write(__version__ + "\n")
