# Loki stores chunks and index natively in GCS

Superseded on 2026-10-13 18:55 UTC by `loki_local_primary_backup_adr.md`: Loki reads and writes a local store again; GCS is a write-only backup. The migration tooling, identity and findings below remain valid.

Date: 2026-10-13 18:00 UTC
Supersedes the archive-only outcome of `loki_gcs_durability_adr.md` (the archive job stays as a safety net until sign-off).

## Context

Loki kept chunks, the TSDB index and the WAL on the node-local volume `main-logging_loki-data`. On 2026-10-13 ephemeral-rebalance moved it to gabriel-pc-wsl for nine hours and it started against an unrelated volume (`loki_pinned_placement_adr.md`). Gabriel's decision: Loki must never run on an empty volume; its data must not depend on one node.

## Decision

1. Chunks and TSDB index (schema v13, 24h tables, `index_` prefix unchanged) use `object_store: gcs` in `gs://<artifacts-bucket>` with `storage_config.object_prefix: loki/cluster/data/` (Loki 3.6.4, experimental flag `-store.object-prefix`, verified to wrap chunks, index, compactor output and delete requests; the bucket root holds no Loki keys). The local volume `main-logging_loki-state` carries only the WAL and caches; `flush_on_shutdown: true` and a 2 minute stop grace period write in-memory chunks out. An embedded 256 MB chunk cache limits egress.
2. Identity: `loki-cluster-storage` service account with object admin only on the managed folder `loki/cluster/` (IaC: `FarDust/personal-stack-infrastructure` PR #10, `loki_gcs_prefix_identity_adr.md` there). Key delivery through the external Docker secret `loki_gcs_sa_key`, mounted 0444 at `/run/secrets/loki_gcs_sa_key`; `swarm-storage-worker` access is not widened. Workload identity federation was rejected for this path because a token refresher on the log-storage path repeats the 2026-10-12 Grafana-to-Loki failure.
3. Retention stays explicit: `LOKI_RETENTION_PERIOD` (168h), compactor retention on with `delete_request_store: gcs`; noncurrent versions under `loki/cluster/` expire after 3 days by bucket lifecycle; soft delete (7 days) applies.
4. History migration with Grafana's first-party `migrate` (`cmd/migrate`, v3.6.4, built from the source tarball sha256 `99da52c3...b283`), idempotent, merging the frost-fang store and the WSL store into one store; unshipped tails (ingester WAL and TSDB head index WAL) recovered by throwaway `-target=write` Loki instances that flush into the target store.
5. The `storage.manager` placement pin stays until Gabriel signs off; the old volume `main-logging_loki-data` and all archives stay untouched.

## Alternatives

- rclone FUSE volume for chunks: the plugin deadlocks under concurrent restores and `fsync` is not durable on `vfs_cache_mode=full`.
- `use_thanos_objstore` with `storage_prefix`: not needed; `object_prefix` was verified end to end.
- Reusing `swarm-storage-worker`: key with delete rights on every prefix, rejected.
- Dual-period schema with the old period local: keeps the local-disk dependency.
- Re-ingestion through the push API: rewrites chunk boundaries and needs `reject_old_samples` relaxed.

## Consequences

- Any non-leader node can run Loki; an empty local volume is harmless (the index is rebuilt from GCS after the first resync).
- Operations and egress cost are small (estimates in the migration report: about 16k writes once, 2-4k writes per day, 2.5 GiB stored, egress dominated by long-range queries).
- `object_prefix` is experimental upstream: keep the image pinned and re-check the bucket root after upgrades.
- `loki-backup` still archives the legacy volume; repoint or stop it after sign-off.

## Verification

Counts through Grafana equal the source stores for 2026-10-12 12:00-13:00 UTC (952,452) and 2026-10-13 07:30-08:30 UTC (163,627); 5-minute coverage has no gap from 06:00 to 17:55 UTC; the compactor created retention markers on GCS; the six Grafana alert rules on log rate, task churn, backup age and role connections are healthy; `rclone lsf` of the bucket root shows no `fake/` or `index/`.
