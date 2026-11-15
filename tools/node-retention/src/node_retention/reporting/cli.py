"""Thin Typer entry point. JSON is stdout; diagnostics use Rich stderr."""

import sys
import time

import typer
from pydantic import ValidationError
from rich.console import Console

from node_retention.reporting.adapters.signals import cancellation_signals
from node_retention.reporting.adapters.supervisor import supervise
from node_retention.reporting.composition import build
from node_retention.reporting.config import ReportSettings
from node_retention.reporting.domain.models import Outcome, ReportCancelled, ReportStatus

app = typer.Typer(help="Bounded read-only stale-resource reporting; never deletes resources.")
err = Console(stderr=True)


@app.command()
def report(worker: bool = typer.Option(False, hidden=True)) -> None:
    """Report stale resources within the original job budget; never deletes."""
    started = time.monotonic()
    try:
        settings = ReportSettings()  # Required NODE_RETENTION_REPORT_* fields; no implicit runtime paths.
    except ValidationError as error:
        fields = [str(e["loc"][0]) if e["loc"] else "configuration" for e in error.errors()]
        err.print("[red]Invalid report configuration fields:[/] " + ", ".join(fields))
        raise typer.Exit(2) from error
    if worker:
        result = build(settings).run(
            deadline_epoch=settings.original_deadline_epoch,
            maximum_seconds=min(settings.maximum_seconds, settings.deadline_epoch - time.time()),
            stale_seconds=settings.stale_seconds,
        )
    else:
        try:
            with cancellation_signals():
                result = supervise(settings)
        except ReportCancelled as error:
            result = Outcome(
                status=ReportStatus.UNKNOWN,
                findings=(),
                reasons=(str(error),),
                trees_examined=0,
                processes_examined=0,
                published_notes=0,
                elapsed_seconds=time.monotonic() - started,
                worker_pid=error.worker_pid,
                worker_termination_verified=error.worker_termination_verified,
            )
            sys.stdout.write(result.model_dump_json() + "\n")
            err.print("[yellow]Report cancelled; owned worker cleanup requested.[/]")
            raise typer.Exit(128 + error.signal_number) from error
    if len(result.findings) > 256:
        result = result.model_copy(
            update={
                "findings": result.findings[:256],
                "status": ReportStatus.PARTIAL,
                "reasons": (*result.reasons, "receipt findings capped; coverage is partial"),
            }
        )
    sys.stdout.write(result.model_dump_json() + "\n")
    if result.status != ReportStatus.COMPLETE:
        err.print("[yellow]Report incomplete:[/] " + "; ".join(result.reasons))
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
