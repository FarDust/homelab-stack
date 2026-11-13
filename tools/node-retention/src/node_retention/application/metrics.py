"""Prometheus textfile rendering for the node_exporter textfile collector.

The guard rewrites the check file every 10 minutes; prune results live in their own file so that a guard run
never erases the result of the last prune (and with it the `NodeRetentionRunFailed` alert).
"""

from __future__ import annotations

from node_retention.config import Settings

CHECK_FILE = "node_retention.prom"
RUN_FILE = "node_retention_run.prom"


def render_metrics(settings: Settings, *, free_bytes: int, now: float) -> str:
    """Free space, floor and the time of the last check (guard or apply)."""
    host = settings.host
    lines = [
        "# HELP node_retention_root_free_bytes Free bytes on the monitored root filesystem.",
        "# TYPE node_retention_root_free_bytes gauge",
        f'node_retention_root_free_bytes{{host="{host}"}} {free_bytes}',
        "# HELP node_retention_root_floor_bytes Policy floor for free bytes on the root filesystem.",
        "# TYPE node_retention_root_floor_bytes gauge",
        f'node_retention_root_floor_bytes{{host="{host}"}} {settings.floor_bytes}',
        "# HELP node_retention_last_check_timestamp_seconds Unix time of the last guard or apply check.",
        "# TYPE node_retention_last_check_timestamp_seconds gauge",
        f'node_retention_last_check_timestamp_seconds{{host="{host}"}} {int(now)}',
    ]
    return "\n".join(lines) + "\n"


def render_run_metrics(settings: Settings, *, now: float, freed_bytes: int, success: bool, planned_bytes: int) -> str:
    """Result of the last prune run, including one that failed before deleting anything."""
    host = settings.host
    lines = [
        "# HELP node_retention_last_run_timestamp_seconds Unix time of the last prune run.",
        "# TYPE node_retention_last_run_timestamp_seconds gauge",
        f'node_retention_last_run_timestamp_seconds{{host="{host}"}} {int(now)}',
        "# HELP node_retention_last_run_success 1 when the last prune run had no failed entry and did not abort.",
        "# TYPE node_retention_last_run_success gauge",
        f'node_retention_last_run_success{{host="{host}"}} {int(success)}',
        "# HELP node_retention_last_run_freed_bytes Bytes freed by the last prune run.",
        "# TYPE node_retention_last_run_freed_bytes gauge",
        f'node_retention_last_run_freed_bytes{{host="{host}"}} {freed_bytes}',
        "# HELP node_retention_last_planned_bytes Bytes the last plan proposed to free.",
        "# TYPE node_retention_last_planned_bytes gauge",
        f'node_retention_last_planned_bytes{{host="{host}"}} {planned_bytes}',
    ]
    return "\n".join(lines) + "\n"
