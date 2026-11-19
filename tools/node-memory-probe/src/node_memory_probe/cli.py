"""Typer entry point and composition root. Rich output goes to stderr; `--json` keeps stdout machine-readable."""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from node_memory_probe import __version__
from node_memory_probe.adapters.docker import DockerCli, DockerJcmd, NoJcmd
from node_memory_probe.adapters.files import JsonState, SnapshotDir, SystemClock, Textfile
from node_memory_probe.adapters.procfs import ProcFs
from node_memory_probe.application.metrics import render
from node_memory_probe.application.probe import Ports, Probe, ProbeOptions, ProbeResult
from node_memory_probe.application.snapshot import build_snapshot
from node_memory_probe.config import Settings
from node_memory_probe.domain.kernel import TriggerPolicy
from node_memory_probe.domain.models import Region

app = typer.Typer(help="Read-only swap residency probe: process x memory region, plus kernel reclaim signals.")
err = Console(stderr=True)


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # host comes from NODE_MEMORY_PROBE_HOST


def build_probe(settings: Settings) -> Probe:
    procfs = ProcFs(settings.proc_root, settings.cgroup_root)
    ports = Ports(
        procs=procfs,
        kernel=procfs,
        jcmd=DockerJcmd(settings.docker_bin, settings.docker_timeout_seconds) if settings.jcmd_enabled else NoJcmd(),
        containers=DockerCli(settings.docker_bin, settings.docker_timeout_seconds),
        state=JsonState(settings.state_path),
        snapshots=SnapshotDir(settings.snapshot_dir),
        clock=SystemClock(),
    )
    options = ProbeOptions(
        host=settings.host,
        jvm_containers=tuple(settings.jvm_containers),
        aliases=dict(settings.aliases),
        top_swap_processes=settings.top_swap_processes,
        top_mappings=settings.top_mappings,
        top_cgroups=settings.top_cgroups,
        top_readers=settings.top_readers,
        cpu_psi_skip_avg10=settings.cpu_psi_skip_avg10,
        trigger=TriggerPolicy(
            swap_free_below=settings.snapshot_swap_free_below_bytes,
            pswpout_above=settings.snapshot_pswpout_pages_per_second,
            swap_free_min_interval_s=settings.snapshot_swap_free_min_interval_seconds,
        ),
        snapshot_max_age_s=settings.snapshot_retention_days * 86400,
        snapshot_budget_bytes=settings.snapshot_budget_bytes,
    )
    return Probe(ports, options)


def _mib(n: int) -> str:
    return f"{n / 1024**2:,.0f}"


def _render_table(result: ProbeResult) -> None:
    mi = result.kernel.meminfo
    err.print(
        f"[bold]{result.host}[/] SwapFree {_mib(mi.get('SwapFree', 0))} MiB, MemAvailable "
        f"{_mib(mi.get('MemAvailable', 0))} MiB, SReclaimable {_mib(mi.get('SReclaimable', 0))} MiB, "
        f"pswpout {result.rates.get('pswpout', float('nan')):.1f}/s"
    )
    regions = list(Region)
    table = Table("process", "pid", "rss MiB", "swap MiB", *[f"{r.value} swap" for r in regions], "heap")
    for m in result.processes:
        heap = "-"
        if m.layout is not None:
            hi = m.layout.heap_info
            heap = m.layout.heap_source + (f" used {_mib(hi.used)}/{_mib(hi.committed)}" if hi else "")
        table.add_row(
            m.label,
            str(m.brief.pid),
            _mib(m.brief.vm_rss),
            _mib(m.brief.vm_swap),
            *[_mib(m.regions[r].swap) if m.regions else "-" for r in regions],
            heap,
        )
    err.print(table)
    for m in result.processes:
        for e in m.errors:
            err.print(f"[yellow]{m.label}: {e}[/]")
    for s in result.skipped:
        err.print(f"[yellow]skipped deep reads: {s}[/]")
    if result.snapshot_reasons:
        err.print(f"snapshot: {result.snapshot_file or '(dry run, not written)'} because {'; '.join(result.snapshot_reasons)}")


@app.command()
def run(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Measure and print; write no state, textfile or snapshot.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the snapshot-shaped result on stdout.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="No table on stderr (the timer's mode).")] = False,
) -> None:
    """Take one sample; publish the textfile (and a snapshot when triggered) unless --dry-run."""
    settings = _settings()
    result = build_probe(settings).run(dry_run=dry_run)
    if not dry_run:
        Textfile(settings.textfile_dir, settings.textfile_name).publish(render(result))
    if as_json:
        sys.stdout.write(json.dumps(build_snapshot(result, settings.top_mappings), sort_keys=True) + "\n")
    if not quiet:
        _render_table(result)


@app.command()
def version() -> None:
    """Print the probe version."""
    sys.stdout.write(f"{__version__}\n")
