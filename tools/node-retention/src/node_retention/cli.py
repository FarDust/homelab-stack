"""Typer entry point and composition root. Human output goes to stderr (Rich); `--json` keeps stdout clean."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from node_retention.adapters.docker_cli import DockerCli
from node_retention.adapters.local import (
    JsonlLedger,
    LocalFileSystem,
    ProcProcesses,
    SystemClock,
)
from node_retention.adapters.textfile import TextfilePublisher
from node_retention.application.applying import Applier
from node_retention.application.metrics import CHECK_FILE, RUN_FILE, render_metrics, render_run_metrics
from node_retention.application.planning import Planner, Ports
from node_retention.application.safety import protected_image_violations
from node_retention.config import Settings
from node_retention.domain.models import Plan
from node_retention.domain.ports import JobLedger

app = typer.Typer(help="Standing disk retention policy for CI/build worker nodes.", no_args_is_help=True)
err = Console(stderr=True)
JsonFlag = Annotated[bool, typer.Option("--json", help="Print the machine-readable result on stdout.")]


def _job_ledger(settings: Settings) -> JsonlLedger:
    return JsonlLedger(settings.ledger_path, malformed_tolerance_s=settings.ledger_malformed_tolerance_hours * 3600)


def _warn_skipped_rows(ledger: JobLedger) -> None:
    if ledger.skipped_lines:
        err.print(
            f"[yellow]job ledger: skipped {len(ledger.skipped_lines)} malformed row(s) older than the tolerance, "
            f"lines {ledger.skipped_lines[:10]}[/]"
        )


def _ports(settings: Settings) -> Ports:
    return Ports(
        fs=LocalFileSystem(),
        procs=ProcProcesses(),
        docker=DockerCli(settings.textfile_helper_image),
        clock=SystemClock(),
        jobs=_job_ledger(settings),
    )


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from NODE_RETENTION_* variables


def _gib(n: int) -> str:
    return f"{n / 1024**3:.2f} GiB"


def _render(plan: Plan) -> None:
    err.print(
        f"[bold]{plan.host}[/] root free {_gib(plan.root_free_bytes)} (floor {_gib(plan.root_floor_bytes)}), "
        f"tool-cache use {_gib(plan.budget_used_bytes)} of {_gib(plan.budget_bytes)}"
    )
    table = Table("category", "size", "age h", "path", "reason")
    for c in plan.candidates:
        table.add_row(c.category.value, _gib(c.size_bytes), f"{c.age_seconds / 3600:.0f}", c.path, c.reason)
    err.print(table)
    for line in plan.protected_image_violations:
        err.print(f"[bold red]image guard failed, image prune refused: {line}[/]")
    err.print(
        f"[bold]plan frees up to {_gib(plan.total_bytes)}[/] in {len(plan.candidates)} entries; {len(plan.skipped)} skipped"
    )


@app.command()
def plan(as_json: JsonFlag = False) -> None:
    """Dry run: print what the policy would delete. Nothing is changed."""
    settings = _settings()
    result = Planner(settings, _ports(settings)).build()
    _render(result)
    if as_json:
        sys.stdout.write(result.model_dump_json(indent=2) + "\n")
    if result.protected_image_violations:
        raise typer.Exit(code=1)


def _shm_gc(settings: Settings, *, dry_run: bool, as_json: bool) -> None:
    ports = _ports(settings)
    result = Planner(settings, ports).build_shm()
    _warn_skipped_rows(ports.jobs)
    _render(result)
    if dry_run:
        err.print("[bold]dry run: nothing removed[/]")
        if as_json:
            sys.stdout.write(result.model_dump_json(indent=2) + "\n")
        return
    if not result.candidates:
        return
    publisher = TextfilePublisher(settings.textfile_dir, settings.textfile_helper_image)
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}"
    applier = Applier(settings, ports, JsonlLedger(settings.ledger_path), publisher)
    manifest = applier.apply(result, run_id, os.getpid(), what="retention-shm-gc")
    err.print(f"freed {_gib(manifest.freed_bytes)} of tmpfs; manifest {applier.manifest_path(run_id)}")
    if as_json:
        sys.stdout.write(manifest.model_dump_json(indent=2) + "\n")
    if any(e.outcome and e.outcome.value == "failed" for e in manifest.entries):
        raise typer.Exit(code=1)


@app.command()
def shm_gc(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print what would be removed; remove nothing.")] = False,
    as_json: JsonFlag = False,
) -> None:
    """Collect idle tmpfs job trees (/dev/shm/agent-jobs): idle time, lane activity, 24 h ceiling and size cap."""
    _shm_gc(_settings(), dry_run=dry_run, as_json=as_json)


@app.command()
def verify_images() -> None:
    """Exit 1 naming each protected image that is missing or has another id; for scripts that prune images."""
    settings = _settings()
    found = protected_image_violations(settings, _ports(settings).docker)
    for line in found:
        err.print(f"[bold red]{line}[/]")
    if found:
        raise typer.Exit(code=1)
    err.print(f"{len(settings.protected_image_refs)} protected image(s) intact")


@app.command()
def apply(as_json: JsonFlag = False) -> None:
    """Plan, write the manifest, delete, record the run in the ledger and publish metrics."""
    settings = _settings()
    ports = _ports(settings)
    publisher = TextfilePublisher(settings.textfile_dir, settings.textfile_helper_image)
    try:
        result = Planner(settings, ports).build()
        _render(result)
        run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.getpid()}"
        applier = Applier(settings, ports, JsonlLedger(settings.ledger_path), publisher)
        manifest = applier.apply(result, run_id, os.getpid())
    except Exception:
        # A run that aborts (unreadable ledger, df or docker failure) is a failed run: the alert must see it.
        publisher.publish(
            RUN_FILE, render_run_metrics(settings, now=ports.clock.now(), freed_bytes=0, success=False, planned_bytes=0)
        )
        raise
    err.print(
        f"freed {_gib(manifest.freed_bytes)}; root free {_gib(manifest.root_free_before)} -> {_gib(manifest.root_free_after or 0)}; "
        f"manifest {applier.manifest_path(run_id)}"
    )
    if as_json:
        sys.stdout.write(manifest.model_dump_json(indent=2) + "\n")
    for line in manifest.protected_image_violations:
        err.print(f"[bold red]image guard failed: {line}[/]")
    if manifest.protected_image_violations or any(e.outcome and e.outcome.value == "failed" for e in manifest.entries):
        raise typer.Exit(code=1)


@app.command()
def guard(as_json: JsonFlag = False) -> None:
    """Publish the free-space metric; run `apply` when the root filesystem is under its floor."""
    settings = _settings()
    ports = _ports(settings)
    free = ports.fs.free_bytes(settings.root_mount.as_posix())
    publisher = TextfilePublisher(settings.textfile_dir, settings.textfile_helper_image)
    publisher.publish(CHECK_FILE, render_metrics(settings, free_bytes=free, now=ports.clock.now()))
    # tmpfs is RAM: it is collected on every guard run (10 minutes), not only when `/` is under its floor.
    shm_failed = False
    try:
        _shm_gc(settings, dry_run=False, as_json=False)
    except Exception as exc:
        shm_failed = True
        err.print(f"[bold red]shm-gc failed: {type(exc).__name__}: {exc}[/]")
    if free >= settings.floor_bytes:
        err.print(f"root free {_gib(free)} is above the floor {_gib(settings.floor_bytes)}; nothing to do")
        if as_json:
            sys.stdout.write('{"action": "none"}\n')
    else:
        err.print(f"[yellow]root free {_gib(free)} is under the floor {_gib(settings.floor_bytes)}; pruning[/]")
        apply(as_json=as_json)
    if shm_failed:
        raise typer.Exit(code=1)
