# ADR: rclone-fixer cache scan budget

Date: 2026-11-12 10:50 UTC

## Context

`main-maintenance_rclone-fixer` (see [the Rust rollout ADR](rclone_fixer_rust_rollout_adr.md)) publishes node-exporter textfile metrics after every 60 s cycle. Part of that publication sizes the rclone VFS cache. It walks `vfs/` and `vfsMeta/` under the plugin cache, then walks `vfs/<remote>` again for each remote. Each walk is bounded by `RCLONE_CACHE_SCAN_MAX_ENTRIES` (default 500000) and `RCLONE_CACHE_SCAN_SECONDS` (default 30).

On 2026-11-12, on the worker that hosts the busiest rclone volumes:

- **The scans never completed.** Every cycle logged `cache scan incomplete for vfs: cache metrics scan exceeded its time budget` after 38,450 to 157,210 entries. The published gauges were `rclone_vfs_cache_scan_incomplete{target="vfs"|"vfsMeta"|"vfs/gcs"} 1`, so no cache size was ever reported.
- **The walk was the controller's entire I/O.** A 100 s `strace -c` of the controller showed 96,700 `getdents64` and about 47,700 each of `open`, `stat`, `fcntl` and `close`. Its own file reads (`rchar`) totalled 58 MB in five days.
- **The walk thrashed its cgroup.** The controller's memory was at its 64M limit, with 0.3 MiB anonymous, about 40 MiB of file cache and about 23 MiB of kernel slab (dentries and inodes). `memory.events max` was 4.86 million and `workingset_refault_file` was 209 million pages.
- **The refaults reached the root disk.** Block reads charged to the cgroup totalled 1.27 TB in five days (310 million reads of about 4 KiB). The node's own monitoring showed 4-8 MB/s of sustained reads from the root disk for the whole period. The directory blocks and inodes of a tree with hundreds of thousands of entries do not fit in 64M, so each cycle re-read them from disk.

Raising the memory limit was evaluated and rejected as the fix. The tree is larger than the 500,000-entry and 30 s budgets, so caching it would need gigabytes per node for a metric that never completes.

## Decision

- Set `RCLONE_CACHE_SCAN_MAX_ENTRIES=1` on the controller service.
  - Each cache walk stops at its first entry and reports `scan_incomplete`, which is what every cycle already reported.
  - `rclone_vfs_cache_available_bytes` comes from a filesystem statistic, not the walk, and stays published.
  - Recovery, probes, cooldowns and the cycle metrics are unchanged.
- Keep the memory budget as decided in the rollout ADR: 64M limit, 8M reservation. Swarm has no per-task swap knob, so the runtime allows swap up to the limit (64M), as in the [memory and swap budgeting ADR](2026-10-11-memory-swap-budgeting.md). Without the walk, the working set is about 2 MiB RSS plus its binary.
- Follow-up in the controller's own repository: size the cache without a full walk every cycle. Options are a single pass shared by the totals and the per-remote values, a slower scan interval than the recovery loop, or rclone's own cache statistics. Re-enable the scan budget here only after that change.

## Alternatives

1. Raise the limit (for example to 512M). Rejected: the walk still exceeds its budget, the cache would need far more memory, and the metric would stay incomplete.
2. `METRICS_ENABLED=false`. Rejected: it also removes the cycle and recovery metrics that the controller publishes.
3. Lengthen `RCLONE_CACHE_SCAN_SECONDS`. Rejected: it makes each cycle read the disk longer.

## Consequences

- No VFS cache size gauge until the controller follow-up lands. There was none in practice before this change, because every scan was incomplete.
- No repository alert or dashboard reads `rclone_vfs_cache_bytes` (checked with `git grep`).
- The deploy restarts only the rclone-fixer tasks, which are global with stop-first updates.

## Verification

- `tests/test_rclone_fixer_scan_budget.py` checks the scan budget and the unchanged memory budget.
- Runtime: the controller's `memory.events max` and `workingset_refault_file` stop growing, its cgroup block reads fall from megabytes per second to near zero, `cycle_completed` keeps appearing every cycle, and the textfile metrics keep being written.

## Rollback

Remove `RCLONE_CACHE_SCAN_MAX_ENTRIES` from the service, which restores the binary default of 500000, and redeploy the single service.
