# ADR: Node memory probe, where swap lives by process and region

Date: 2026-11-19 02:10 UTC

## Context

On the build worker (31 GiB RAM, 16 GiB swap, `vm.swappiness=10`, cgroups v2, container `memory.max` and `memory.swap.max` unset, `memory.low` 0) the game-server JVM and several other processes end up with pages in swap. Existing signals (node_exporter, cAdvisor, Netdata) show per-container totals but not which part of a process left RAM (Java heap, class metadata, code cache, thread stacks, libraries, other native memory) or what the kernel was doing when it happened. `/proc/<pid>/smaps` of other users' processes is denied to the unprivileged operator account, so the answer needs root, read-only.

## Decision

A typed tool, `tools/node-memory-probe` (uv, Python 3.13, pydantic-settings, Typer, Rich), run as a systemd **system** unit and timer every 60 s (nice 19, idle I/O class, no network, `ProtectSystem=strict`, writes only the Prometheus textfile and its own state and snapshot directory).

- Processes: the largest JVM of each configured container (always probed) plus the top 5 swap holders by `VmSwap`.
- Regions: each mapping is classified from smaps shape (adjacent anonymous groups, permissions, size). The heap is found from the JVM flags (`-Xmx`) and, for the primary JVM, from `jcmd GC.heap_info` via `docker exec` when available (skipped silently otherwise); the classification is a documented heuristic, not exact accounting.
- Kernel side: `pswpin`/`pswpout` rates from `/proc/vmstat` deltas, SwapFree, SwapCached, Slab, SReclaimable, Cached, MemAvailable, PSI memory and I/O, per-cgroup swap and reclaim rates, top readers by storage reads and metadata scanners.
- Overhead guard: per-mapping reads and `jcmd` are skipped while CPU PSI `some avg10` is at or above the configured threshold.
- Output: the textfile `node_memory_probe.prom` (`node_memory_probe_*{process,region}`) by atomic rename in the directory node_exporter already reads, and trigger snapshots (SwapFree under 3 GiB or `pswpout` above 100 pages/s; top 30 mappings by swap) kept 14 days or 200 MiB.
- Read-only: the probe reads `/proc`, cgroupfs and `jcmd` answers only; it never signals a process, restarts a container or touches the observed workload.

## Alternatives

- Netdata/cAdvisor only: no per-region view, rejected as insufficient for the question.
- `jcmd VM.native_memory` (NMT): exact for the JVM but needs a JVM restart flag (`-XX:NativeMemoryTracking`) on a server that must not be restarted; kept as a later option.
- Ad hoc `smem`/`pmap` runs: not continuous, miss the moment pages leave RAM.
- A user unit like `node-retention`: cannot read other users' smaps; a system unit is required.

## Consequences

- One more root-run unit; its surface is read-only and network-less, and its rollback is `systemctl disable --now node-memory-probe.timer`.
- Region labels are heuristic; the snapshot keeps the raw top mappings so a reader can re-judge.
- Cost per run is bounded by the skip guard; metrics cardinality is bounded by top-N processes and a fixed region set.

## Verification

Unit tests with synthetic smaps and fixtures (`tools/node-memory-probe/tests`); a dry run on the node; the metrics visible in Prometheus; the timer showing successful runs in the journal. The first reading is recorded in the vault learning for 2026-11-19.
