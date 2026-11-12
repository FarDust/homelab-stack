# ADR: Netdata parent image and memory budget

Date: 2026-11-12 09:40 UTC

## Context

The Netdata parent (`main-bridges_netdata-parent`) receives streams from three child agents and runs health checks for them. On 2026-11-12 its node showed load about 5 on 6 cores with CPU half idle, I/O wait 16-18 %, node `io some` pressure 25-31 % and 10 GiB of 16 GiB swap in use with constant swap-in and swap-out.

Evidence from the parent's cgroup and its own API, five days after its last start (image `netdata/netdata:v2.12.1`, limit `3G`, no reservation):

- `memory.current` equal to `memory.max` (3 GiB); `memory.swap.current` 3 GiB, the largest single swap holder on the node; `memory.events max` 8.56 million; `workingset_refault_file` 1.06 billion pages; `pgmajfault` 31 million; cgroup `io some` pressure 17-18 %; about half a CPU core used continuously.
- `memory.stat`: 2.6 GiB anonymous plus 3 GiB swapped anonymous memory, leaving about 0.5 GiB of page cache for a 4.7 GiB `netdata-meta.db` with a 0.9 GiB WAL. The cache directory held 8.4 GiB in total.
- The `netdata.memory` chart grew monotonically after the start: `metadata` 0.33 GB to 2.23 GB, `uuid` 61 MB to 295 MB, `strings` 58 MB to 284 MB, `labels` 16 MB to 119 MB, `dbengine` 0.66 GB to 1.59 GB. The total went from about 1.5 GB to about 5 GB, roughly 16 MB/h of metadata alone. Metadata is not a cache, so neither the limit nor dbengine memory protection can reclaim it.
- One child alone had 56,646 retained chart instances and 127,305 dimensions over ten days, 47,897 of them `cgroup.*` instances from 1,426 distinct containers: short-lived CI and task containers each leave a full set of cgroup charts, and many of those charts carry alerts.

Upstream release notes for v2.12.2 describe this mechanism: alert evaluation reset the last-access time of obsolete charts, so obsolete charts with alerts were never cleaned up, and on hosts with container churn the charts and their metadata kept growing on parents (netdata/netdata PR 24273). The same release fixes metadata cleanup passes that could stall and checks the WAL size far less often during cleanup (PR 24227). v2.12.3 adds further cleanup fixes for obsolete charts and ephemeral hosts.

The thrash loop was: unbounded metadata growth fills the 3 GiB resident limit, the kernel swaps the anonymous working set (Docker allows swap equal to the limit) and evicts the page cache of the SQLite and dbengine files, and every metadata and query pass refaults them from the lvmcache SSD. On 2026-11-12 09:27 UTC a large contexts API query pushed the process over the limit and the kernel OOM-killed it inside its cgroup (`CONSTRAINT_MEMCG`).

## Decision

- Pin the parent to `netdata/netdata:v2.12.3` by tag and digest (`sha256:c7eab00e20901eb60595ebae0fbfe88e59464e663924461874719d40de0735d2`), the current stable release that contains the parent metadata fixes.
- Keep the resident limit at `3G` and add a `2G` memory reservation, so the scheduler accounts for the parent's measured steady state and keeps room for it on the node.
- Swap budget: Swarm exposes no per-task swap control, and the runtime currently allows swap equal to the limit (3 GiB). That swap allowance is accepted as an implicit, uncontrolled budget and documented here instead of being presented as a limit, as required by [memory and swap budgeting](2026-10-11-memory-swap-budgeting.md). With the growth fixed the parent should not reach the limit, which keeps that swap unused.
- Keep the dbengine retention, page cache, tiers and health settings unchanged, and keep the existing dbengine and metadata files: no history is deleted.

## Alternatives

1. Raise the limit (for example to 6 GiB). Rejected: it only delays the same growth, doubles the implicit swap allowance and takes memory from the game server that shares the node.
2. Shrink dbengine page cache or retention. Rejected: dbengine was not the growing allocation, the page cache is already the 256 MiB floor per the memory ADR, and it would reduce the history the operator uses.
3. Disable health on the parent or drop cgroup charts on children. Rejected for now: it removes alerts and container visibility. Filtering ephemeral containers on the children is a separate host change, to be considered only if metadata still grows after this upgrade.
4. Restart the parent periodically. Rejected: a bounce is not a fix and loses streaming continuity.

## Consequences

- The deploy restarts only the Netdata parent; children reconnect and replicate the gap.
- The existing 4.7 GiB metadata database is kept; the fixed cleanup should remove obsolete rows over time, but SQLite does not shrink the file without a vacuum.
- If `netdata.memory` metadata keeps growing linearly on v2.12.3, the next step is filtering ephemeral cgroups on the children, or an upstream report through the owning workflow.

## Verification

- `tests/test_netdata_parent_budget.py` checks the pinned image version and digest, the limit and reservation, and this record.
- Runtime, for at least 15 minutes after convergence: cgroup `memory.current` well below `memory.max`, `memory.events max` constant, the `netdata.memory` metadata series flat, node `io some` pressure, load average, swap-in/out and SSD read rate lower than before, and all four nodes still streaming with health alerts present.

## Rollback

Restore the previous service definition and redeploy `main-bridges`: image `netdata/netdata:v2.12.1`, `deploy.resources.limits.memory: 3G` and no `reservations` entry.
