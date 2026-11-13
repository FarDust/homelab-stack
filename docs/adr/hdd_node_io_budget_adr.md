# ADR: I/O and memory budget of a worker whose Docker root sits on a hard disk

Date: 2026-11-12 23:50 UTC

## Context

One Swarm worker keeps its Docker root, `/tmp` and `/var/log` on a single 7,200 rpm hard disk. The Docker volume has an SSD cache in writethrough mode, so reads are fast and every write still waits for the hard disk, which sustains roughly 150 random writes per second. The per-container figures below are cgroup `io.stat` operations on the logical volume: sequential appends are merged before they reach the disk, so they can exceed that number, while scattered small writes and fsyncs cannot. On 2026-11-12 the node showed load 5-9 on 6 cores with `io some` pressure of 20-60 %, and agent jobs were queued one at a time behind a lock for the rest of the day instead of the cause being established. This record is the investigation that should have happened that morning.

Measured on 2026-11-12 (node exporter history, cgroup v2 `io.stat`, Netdata per-cgroup charts):

- **Netdata parent, 10:51-12:45 UTC, ended.** After the upgrade recorded in [Netdata parent image and memory budget](netdata_parent_memory_budget_adr.md), the fixed release cleaned up the metadata that the old release had leaked. Its cgroup wrote 25-32 MB/s (about 1,550 write operations/s) for 90 minutes; the disk was 88 % busy over the 11:00 hour and node pressure averaged 58 %. From 13:00 UTC it wrote 0.1-1.9 MB/s. In-memory metadata fell from 316 MB to 149 MB and has been flat since 19:00 UTC; the metadata database went from 4.73 GB to 3.50 GB with a 16 MB WAL. The cleanup converged; it is not looping.
- **The fixed release bounds the cardinality itself.** Its log shows 847 `EXTREME CARDINALITY PROTECTION` actions that day, clearing long-gone container instances (one child had 1,182 `cgroup.cpu` instances, 88 % of them ephemeral).
- **Idle baseline, 18:00-21:00 UTC:** disk 12 % busy, node `io some` 4 %. The steady services do not saturate the disk.
- **Evening pressure, 21:00 UTC onwards (23-52 %): our own jobs.** In a 60-second sample at 23:41 UTC a throwaway PostgreSQL test container with its data in an anonymous volume wrote 143 MB in 6,006 operations: 63 % of all bytes written to the Docker volume. The Netdata parent wrote 2.5 MB (1 %).
- **Live capture, 23:58 UTC, several jobs running at once:** disk 105 % busy, queue 11, write wait 58 ms, both SSDs 5 % busy. 66 % of the disk's write operations (430/s, 282 MB in 45 s) went to `/tmp`, which sits on the hard disk with no cache: job checkouts, dependency installs and evidence files. The Docker volume took 214 writes/s (job container layers, five throwaway PostgreSQL containers, ClickHouse). The Netdata parent wrote 121 of 9,556 operations (1.3 %).
- **Steady background writers that consume the disk's budget for nothing:**
  - ClickHouse self-telemetry: 100-340 write operations/s around the clock for at least 48 hours. In ten minutes it created 471 parts in `asynchronous_metric_log`, `part_log`, `metric_log`, `trace_log` and `text_log`; those tables hold 58 GB. The service ran the stock configuration from a floating `latest` tag.
  - The Docker daemon ran with `"debug": true` since August: 2,224 journal lines per minute onto the same disk.
- 1,799 dangling anonymous volumes were left on the node by removed job containers.

Root cause of the saturation, by proof level:

1. Proven: every write on the node's Docker root, `/tmp` and `/var/log` shares one hard disk (about 150 write operations/s), so any fsync-heavy writer saturates it.
2. Proven: the morning event was the one-time Netdata metadata cleanup (ended 12:45 UTC).
3. Proven for two sampled windows (23:41 and 23:58 UTC), likely for the rest of the evening: the later pressure came from our own jobs writing scratch data to `/tmp` and to container volumes on the hard disk.
4. Proven: ClickHouse self-telemetry and daemon debug logging were the largest steady writers; they take budget without saturating the disk alone.

## Decision

- Remove the ClickHouse self-telemetry tables through `stacks/main/configs/clickhouse/system-logs.xml` (mounted into `config.d`): `trace_log`, `text_log`, `metric_log`, `asynchronous_metric_log`, `part_log`, `latency_log`, `error_log`, `query_metric_log`, `query_thread_log`, `processors_profile_log` and `background_schedule_pool_log`. Keep `query_log` and `crash_log`. Keep the existing tables on disk: dropping them deletes data and is the operator's decision.
- Pin ClickHouse to the exact release and digest that was running under `latest` (`26.3.9.8`), so the configuration rollout cannot also upgrade the database.
- Add two alerts: `HostIoPressureSustained` (tasks waiting on I/O more than 30 % of the time for 30 minutes) and `HostDiskSaturated` (a physical disk more than 90 % busy for 30 minutes). On 2026-11-12 the first would have fired during the 11:00 hour (58 % against a 30 % threshold). The second is a backstop for a disk pinned for half an hour; that morning's hourly average was 88 %. Busy time is a saturation signal for rotating disks; on solid-state disks read it together with the pressure alert.
- Keep job scratch (checkouts, dependency trees, caches, browser profiles) on a memory-backed filesystem such as `/dev/shm`, sized against available memory, and run throwaway test databases in memory; see [ephemeral test databases belong in memory](../troubleshoot/ephemeral-test-databases-belong-in-memory.md).
- Host change applied outside this repository on the same day: daemon debug logging off (`"debug": false`, applied with a configuration reload, no daemon restart; 2,224 to 7 journal lines per minute).

### Amendment 2026-11-13 00:25 UTC: the bottleneck moved to memory

The jobs moved their scratch to `/dev/shm` at about 00:05 UTC. The hard disk went quiet, and within minutes the node was swapping out instead:

| Signal | 23:58 UTC (scratch on `/tmp`) | 00:08-00:20 UTC (scratch on tmpfs) | 00:22 UTC (settled) |
|---|---|---|---|
| Hard disk busy | 105 % | quiet (2 MB/s written) | quiet |
| Shmem | 0.1 GB | 2.7 GB | 1.2 GB |
| Swap used | 6.5 GB | 6.5 to 11.8 GB | 10.8 GB |
| Swap-out to the SSD | 0 | 6-10 MB/s over 5 minutes, bursts of 42-76 MB/s | 0 |
| `memory some` pressure | 0.3 % | 32-35 % over 5 minutes, 42-60 % peaks | 1 % |
| `io some` pressure | 74 % | 86-92 % (swap I/O) | 14 % |
| `cpu some` pressure | 16 % | 5 % | 44 % |

- Consumers of the burst (proven): tmpfs scratch (4.2 GB in the job directory, 1.7 GB of it already swapped, because tmpfs pages are swap-backed), each job's own memory (one measured job cgroup: 1.2 GB) and a 2 GB language-model runner that loaded at 00:13 UTC. No service was near its limit. The largest standing claim is the game server's JVM, started with a 12 GB maximum heap and no cgroup limit (4.8 GB resident plus 2.5 GB swapped at the time).
- Why the kernel swapped with "10 GB available" (proven from `/proc/meminfo`): `MemAvailable` included 5.3 GB of reclaimable slab that stayed flat for two hours, and the droppable file cache was about 5.8 GB. With free memory at zero, reclaim took cold anonymous and tmpfs pages. No compressed swap existed, so every page went to the SSD volume that also holds the root filesystem.
- The earlier admission rule ("start while `MemAvailable` is at least 4 GB") used the wrong signal.

Decision for agent jobs on this node:

- **Admission**, measured at job start, all terms required: `memory some avg10 < 10`, `cpu some avg10 < 25`, swap-out below 1 MB/s (`pswpout` delta over 5 s under 1,280 pages), `MemAvailable - SReclaimable >= job footprint + 3 GB`, `SwapFree >= 4 GB`. No lock: a job that is not admitted retries on the signal.
- **Budget:** 8 GB for agent jobs, which is three concurrent jobs with scratch on tmpfs (about 2.5 GB each: 1.2 GB of processes, up to 1.1 GB of scratch, a small database).
- **Footprint per job:** throwaway PostgreSQL on a 256 MB tmpfs (measured use 0.05 GB), `NODE_OPTIONS=--max-old-space-size=1536` for compilers and bundlers, one browser, `--memory 3g --memory-swap 3g` on job containers, and the scratch directory deleted when the job ends.
- **Where scratch belongs:** small hot data (database files, browser profiles) on tmpfs; large trees (checkouts, dependency directories, package caches) on an SSD-backed directory once the root volume has room. It had 6.9 GB free; about 24 GB of it is CI caches and old build directories in the job user's home that their owners can prune.
- **Compressed swap:** zswap enabled at runtime at 00:20:48 UTC (`zstd`, `zsmalloc`, pool at most 20 % of memory) so cold pages are compressed in memory before any is written to the SSD. Runtime only; it reverts at reboot. Rollback: `echo 0 > /sys/module/zswap/parameters/enabled`. Making it persistent (kernel command line or a boot-time unit) is the operator's decision. Its effect is not measured yet: no swap-out happened between enabling it and the end of this record; compare `zswpout` with `pswpout` in `/proc/vmstat` on the next burst.

Left to the operator: a memory limit or a smaller heap for the game server (12 GB maximum heap of 31 GB; needs a server restart with no players online), and an idle-unload time for the model runner that has none configured.

## Alternatives

1. Keep serialising jobs behind a lock. Rejected: it hides the consumer, makes every job slower and outlived the event it was added for by half a day.
2. Throttle the writer with cgroup `io.max`. Tried on the Netdata parent that morning and reverted: throttled tasks count as stalled, so node pressure and load rose and the cleanup stopped advancing.
3. Switch the SSD cache to writeback. It would absorb random writes, but dirty blocks would then exist only on one worn consumer SSD without power-loss protection. Left to the operator.
4. Move the Docker root or the busiest volumes to solid-state storage. The lasting fix for the shared-disk limit; needs hardware or a storage migration, so it is left to the operator.
5. Filter ephemeral container charts on the Netdata children. Not needed now: metadata is flat on the fixed parent release. Reconsider if the `netdata.memory` metadata series grows again.
6. Vacuum the Netdata metadata database offline. Optional: the file is 3.5 GB for 149 MB of live metadata, and it needs a parent stop plus a full rewrite on the hard disk.

## Consequences

- ClickHouse restarts once (stop-first). Its history of internal metrics, traces and server text logs stops growing; queries against those tables return only old rows.
- The alerts add one notification per saturated node plus one per pinned disk and stay silent on a merely busy node (the normal level here is 4-25 %).
- The shared hard disk remains the node's limit until the operator decides on storage.

Left to the operator, with the exact command and the risk:

- Free the 58 GB of old self-telemetry: `TRUNCATE TABLE system.trace_log` (and `text_log`, `asynchronous_metric_log`, `part_log`, `metric_log`, plus the numbered leftovers such as `system.trace_log_7`) in `clickhouse-client`. Risk: that diagnostic history is gone; nothing else reads it. Tables above 50 GB need `max_table_size_to_drop` raised for the statement.
- Remove the dangling anonymous volumes: `docker volume prune -f` on the node. Risk: deletes data of any anonymous volume not attached to a container at that moment.
- Cache mode: `lvchange --cachemode writeback <vg>/<lv>`; back with `--cachemode writethrough`. Risk: a power loss or SSD failure can corrupt the Docker root.

## Verification

- `tests/test_clickhouse_system_logs.py` checks the pinned image, the mounted override, the removed and kept tables, the alerts and this record. `tests/prometheus/io-pressure-alerts.test.yml` exercises both alerts with `promtool test rules`.
- The override was checked against the exact image with `clickhouse extract-from-config`: the removed keys are absent, `query_log` and `crash_log` remain.
- Runtime: ClickHouse write operations per second and new parts per ten minutes before and after, node `io some` pressure and disk busy time over a stated window, consumers of ClickHouse healthy.

## Rollback

- ClickHouse: remove the `clickhouse_system_logs` entry from the service and from `configs:` (or delete `system-logs.xml` lines for the tables to restore) and redeploy the one service with `cluster-utils deploy service clickhouse --stack-name main-storage`. The image pin can stay.
- Alerts: remove the two rules from `alert.rules` and redeploy the Prometheus service.
- Swarm configs are immutable: a changed file needs a `CONFIG_VERSION` the service has not used yet (`--bump-config` when the current one is already deployed for that service).
- Daemon debug logging: set `"debug": true` in the daemon configuration and reload the daemon.
