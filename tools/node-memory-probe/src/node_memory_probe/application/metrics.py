"""Render a probe result in the Prometheus text format; prometheus_client owns the exposition format."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest

from node_memory_probe import __version__
from node_memory_probe.application.probe import ProbeResult
from node_memory_probe.domain.kernel import MEMINFO_FIELDS

P = "node_memory_probe"


def render(result: ProbeResult) -> str:
    reg = CollectorRegistry()

    def g(name: str, doc: str, labels: tuple[str, ...] = ()) -> Gauge:
        return Gauge(f"{P}_{name}", doc, labels, registry=reg)

    g("build_info", "Probe version.", ("version",)).labels(__version__).set(1)
    g("last_run_timestamp_seconds", "Unix time of the run that wrote this file.").set(result.timestamp)
    g("run_duration_seconds", "Wall time of the run.").set(result.duration_s)
    g("deep_skipped", "1 when per-mapping reads were skipped because CPU pressure was high.").set(
        1 if result.skipped else 0
    )

    info = g("process_info", "Selected process identity.", ("process", "pid", "comm", "container", "primary"))
    rss = g("vm_rss_bytes", "VmRSS of the process.", ("process",))
    swap = g("vm_swap_bytes", "VmSwap of the process.", ("process",))
    r_swap = g("swap_bytes", "Swapped-out bytes by memory region (from smaps).", ("process", "region"))
    r_rss = g("rss_bytes", "Resident bytes by memory region (from smaps).", ("process", "region"))
    r_pss = g("pss_bytes", "Proportional set size by memory region.", ("process", "region"))
    heap_used = g("heap_used_bytes", "Java heap used (jcmd GC.heap_info).", ("process",))
    heap_committed = g("heap_committed_bytes", "Java heap committed (jcmd GC.heap_info).", ("process",))
    heap_reserved = g("heap_reserved_bytes", "Size of the address range classified as java heap.", ("process",))
    meta_used = g("metaspace_used_bytes", "Metaspace used (jcmd GC.heap_info).", ("process",))
    meta_committed = g("metaspace_committed_bytes", "Metaspace committed (jcmd GC.heap_info).", ("process",))
    source = g("heap_source", "How the heap range was found: jcmd, xmx, max_ram_percentage, none.", ("process", "source"))
    jcmd_ok = g("jcmd_ok", "1 when jcmd GC.heap_info answered this run.", ("process",))
    errors = g("process_read_errors", "Errors met while reading the process this run.", ("process",))
    for m in result.processes:
        b = m.brief
        info.labels(m.label, str(b.pid), b.comm, m.container, "1" if m.primary else "0").set(1)
        rss.labels(m.label).set(b.vm_rss)
        swap.labels(m.label).set(b.vm_swap)
        errors.labels(m.label).set(len(m.errors))
        for region, usage in m.regions.items():
            r_swap.labels(m.label, region.value).set(usage.swap)
            r_rss.labels(m.label, region.value).set(usage.rss)
            r_pss.labels(m.label, region.value).set(usage.pss)
        if m.layout is not None:
            source.labels(m.label, m.layout.heap_source).set(1)
            if m.layout.heap is not None:
                heap_reserved.labels(m.label).set(m.layout.heap.size)
            hi = m.layout.heap_info
            if hi is not None:
                heap_used.labels(m.label).set(hi.used)
                heap_committed.labels(m.label).set(hi.committed)
                if hi.metaspace_used is not None and hi.metaspace_committed is not None:
                    meta_used.labels(m.label).set(hi.metaspace_used)
                    meta_committed.labels(m.label).set(hi.metaspace_committed)
        if m.jcmd_ok is not None:
            jcmd_ok.labels(m.label).set(1 if m.jcmd_ok else 0)

    vm_rate = g("vmstat_rate", "Per-second rate of a /proc/vmstat counter since the last run.", ("counter",))
    for counter, value in sorted(result.rates.items()):
        vm_rate.labels(counter).set(value)
    if "pswpout" in result.rates:
        g("pswpout_pages_per_second", "Pages swapped out per second since the last run.").set(result.rates["pswpout"])
    if "pswpin" in result.rates:
        g("pswpin_pages_per_second", "Pages swapped in per second since the last run.").set(result.rates["pswpin"])
    meminfo = g("meminfo_bytes", "Selected /proc/meminfo fields at the run.", ("field",))
    for name in MEMINFO_FIELDS:
        if name in result.kernel.meminfo:
            meminfo.labels(name).set(result.kernel.meminfo[name])
    pressure = g("pressure_ratio", "PSI share of time stalled (0-1).", ("resource", "kind", "window"))
    for resource, p in result.kernel.pressure.items():
        pressure.labels(resource, "some", "10s").set(p.some_avg10 / 100)
        pressure.labels(resource, "some", "60s").set(p.some_avg60 / 100)
        if p.full_avg10 is not None and p.full_avg60 is not None:
            pressure.labels(resource, "full", "10s").set(p.full_avg10 / 100)
            pressure.labels(resource, "full", "60s").set(p.full_avg60 / 100)

    cg_swap = g("cgroup_swap_bytes", "memory.swap.current of the cgroups holding the most swap.", ("cgroup",))
    cg_mem = g("cgroup_memory_bytes", "memory.current of those cgroups.", ("cgroup",))
    cg_change = g("cgroup_swap_change_bytes_per_second", "Change of memory.swap.current per second.", ("cgroup",))
    cg_scan = g("cgroup_pgscan_pages_per_second", "Pages scanned by reclaim in the cgroup per second.", ("cgroup",))
    for row in result.cgroups:
        cg_swap.labels(row.label).set(row.cgroup.swap_current)
        cg_mem.labels(row.label).set(row.cgroup.memory_current)
        if row.swap_change_per_s is not None:
            cg_change.labels(row.label).set(row.swap_change_per_s)
        if row.pgscan_per_s is not None:
            cg_scan.labels(row.label).set(row.pgscan_per_s)

    readers = g("top_reader_bytes_per_second", "Storage reads per second of the heaviest readers, by comm.", ("comm",))
    for comm, value in result.readers:
        readers.labels(comm).set(value)
    scanners = g("scanner_processes", "Running metadata-walking processes (du, find, rsync...).", ("comm",))
    for comm, count in sorted(result.scanners.items()):
        scanners.labels(comm).set(count)
    g("snapshot_triggered", "1 when this run's conditions asked for a snapshot.").set(1 if result.snapshot_reasons else 0)
    if result.snapshot_bytes_kept is not None:
        g("snapshots_bytes", "Bytes held by retained snapshots.").set(result.snapshot_bytes_kept)
    return generate_latest(reg).decode("utf-8")
