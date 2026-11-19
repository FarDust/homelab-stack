"""The compact JSON written when swap is low or pages are leaving RAM fast. No command lines, no environment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from node_memory_probe.domain.models import ProcessMemory

if TYPE_CHECKING:
    from node_memory_probe.application.probe import ProbeResult

SCHEMA = "node-memory-probe/snapshot/1"


def snapshot_name(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("snapshot-%Y%m%dT%H%M%SZ.json")


def _process(m: ProcessMemory, top: int) -> dict[str, Any]:
    layout = m.layout
    info = layout.heap_info if layout else None
    return {
        "label": m.label,
        "container": m.container,
        "comm": m.brief.comm,
        "pid": m.brief.pid,
        "primary": m.primary,
        "vm_rss": m.brief.vm_rss,
        "vm_swap": m.brief.vm_swap,
        "is_jvm": m.is_jvm,
        "heap_source": layout.heap_source if layout else None,
        "heap_range": [hex(layout.heap.start), hex(layout.heap.end)] if layout and layout.heap else None,
        "heap_committed": info.committed if info else None,
        "heap_used": info.used if info else None,
        "metaspace_used": info.metaspace_used if info else None,
        "metaspace_committed": info.metaspace_committed if info else None,
        "jcmd_ok": m.jcmd_ok,
        "regions": {r.value: {"rss": u.rss, "pss": u.pss, "swap": u.swap, "mappings": u.mappings} for r, u in m.regions.items()},
        "top_mappings": [
            {
                "start": hex(c.mapping.start),
                "end": hex(c.mapping.end),
                "perms": c.mapping.perms,
                "path": c.mapping.path,
                "region": c.region.value,
                "size": c.mapping.size,
                "rss": c.mapping.rss,
                "swap": c.mapping.swap,
            }
            for c in m.top_mappings[:top]
        ],
        "errors": m.errors,
    }


def build_snapshot(result: ProbeResult, top: int) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "host": result.host,
        "timestamp": datetime.fromtimestamp(result.timestamp, UTC).isoformat(),
        "reasons": result.snapshot_reasons,
        "meminfo": result.kernel.meminfo,
        "rates_per_second": result.rates,
        "pressure": {
            k: {"some_avg10": p.some_avg10, "some_avg60": p.some_avg60, "full_avg10": p.full_avg10}
            for k, p in result.kernel.pressure.items()
        },
        "processes": [_process(m, top) for m in result.processes],
        "cgroups": [
            {
                "label": row.label,
                "swap_current": row.cgroup.swap_current,
                "memory_current": row.cgroup.memory_current,
                "swap_change_per_s": row.swap_change_per_s,
                "pgscan_per_s": row.pgscan_per_s,
            }
            for row in result.cgroups
        ],
        "top_readers_bytes_per_s": dict(result.readers),
        "scanner_processes": result.scanners,
        "skipped": result.skipped,
    }
