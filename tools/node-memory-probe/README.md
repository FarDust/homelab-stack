# node-memory-probe

Read-only probe that answers where a node's swap lives: process x memory region (java heap, class space,
metaspace, code cache, thread stacks, malloc arenas, libraries, mapped files, other native), plus what the kernel
was doing when pages left RAM (pswpin/pswpout rates, SwapFree, SwapCached, slab, Cached, PSI, per-cgroup swap).
Decision record: [docs/adr/node_memory_probe_adr.md](../../docs/adr/node_memory_probe_adr.md).

```bash
uv run --project tools/node-memory-probe node-memory-probe run --dry-run   # table on stderr, writes nothing
uv run --project tools/node-memory-probe node-memory-probe run --json      # snapshot-shaped JSON on stdout
```

Reading `/proc/<pid>/smaps` of other users needs root, so the node runs it as a system unit
(`deploy/node-memory-probe.service`, timer every 60 s, nice 19, idle I/O, no network). Output: the Prometheus
textfile `node_memory_probe.prom` (`node_memory_probe_*{process,region}`) written by atomic rename, and trigger
snapshots (SwapFree under 3 GiB or pswpout above 100 pages/s) under `/var/lib/node-memory-probe/snapshots`,
kept 14 days / 200 MiB. Settings: `deploy/node-memory-probe.env.example`.

Install: copy the project to `/opt/node-memory-probe` (root-owned), `uv sync --frozen` there, install the unit,
timer and `/etc/node-memory-probe.env`, then `systemctl enable --now node-memory-probe.timer`.
Rollback: `systemctl disable --now node-memory-probe.timer` (the probe changes nothing else).

Run the tests with `uv run --project tools/node-memory-probe pytest`.
