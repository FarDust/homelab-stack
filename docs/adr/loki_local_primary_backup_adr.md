# Loki primary store is local; GCS is a write-only backup; a second node holds a warm copy

Date: 2026-10-13 18:55 UTC
Supersedes `loki_gcs_native_storage_adr.md` (Loki reading chunks and index from GCS). The migration tooling and findings in that ADR remain valid.

## Context

The 17:40 UTC cutover put Loki's chunks and TSDB index in GCS. Gabriel's correction: the intent was a backup in GCP, with enough local retention and a distributed local copy, not queries served from GCS. Every Grafana range query would read chunks from the Santiago bucket (internet egress, about USD 0.12 per GiB read), and the embedded chunk cache is memory only, so a dashboard that refreshes a long range re-reads the same chunks. Retention was also too short (168h, inherited from the old stack default).

## Decision

1. Primary store local again: `object_store: filesystem`, chunks under `/var/lib/loki/chunks`, TSDB index in `chunks/index` and `/var/lib/loki/index`, WAL in `/var/lib/loki/wal`, all inside the host directory `/var/lib/docker/loki-store` bind-mounted into the Loki task. The service stays on a storage-manager node that is not the leader (frost-fang) and is skipped by ephemeral-rebalance (`loki_pinned_placement_adr.md`).
2. Retention 90 days: `LOKI_RETENTION_PERIOD=2160h` in `.env`, `.env.example` and the stack default; compactor retention on, `delete_request_store: filesystem`, `max_query_length: 2161h` so a query may span the whole window (the default is 721h). Expected size about 26 GiB at 0.3 GiB per day compressed; frost-fang's Docker volume has 244 GB free.
3. Seeding: the whole merged store was copied from GCS into the local directory with Grafana's `migrate` (2.7 GB, 15,236 chunks, 14 minutes, a one-off read of about 2.7 GB). Verification on a read-only Loki over a hardlinked copy matched the GCS-backed Grafana counts exactly: 24 hour totals ending 2026-10-09 / 10 / 11 / 12 / 13 00:00 UTC of 10,455,417 / 9,730,201 / 10,479,257 / 16,290,963 / 14,143,768 lines, and the 1 hour windows ending 2026-10-12 13:00 (952,452), 2026-10-13 07:30 (1,279,723) and 08:30 (163,627). A catch-up pass after the cutover brought in what GCS had received since, and 5-minute coverage has no gap from 17:50 to 18:50 UTC.
4. Guard against an empty start: the Loki task bind-mounts both the data directory and the marker file `/var/lib/docker/loki-store/.loki-store-initialized`. Swarm does not create missing bind sources, so the task is rejected with `invalid mount config for type "bind": bind source path does not exist` on any node that has not been seeded; the marker is created by hand only after seeding or restoring. This needs no custom image and no shell (the Loki image is distroless). Tested on 2026-10-13 with a throwaway service.
5. Backup and warm copy (separate change in this ADR's family, see the sync section once deployed): a write-only copy of new immutable files to `gs://<artifacts-bucket>/loki/cluster/backup-store/` with the scoped identity, and a copy to a second persistent node for failover. Grafana never reads from GCS. The previous GCS-primary data under `loki/cluster/data/`, the archives under `backup/` and `backup-wsl/`, the old volumes and the scratch copies stay untouched until Gabriel signs off.

## Alternatives

- Keep GCS as primary with a local disk chunk cache: a cache of this size is possible but misses on cold ranges still bill egress, and the node would still depend on GCS availability to answer queries.
- Garage (Rust, S3 compatible, 2 to 3 node replication) as a self-hosted replicated object store for Loki: gives true multi-node primary storage and no rsync window, but needs three nodes of persistent disk to be worthwhile (the cluster has two persistent nodes, one of them a starved 2-CPU manager), adds a new stateful service whose own loss would take the logs with it, and Loki would still need an object-store client path and credentials. Rejected for now; revisit if a third persistent node appears.
- Network disk or rclone mount for the primary: the rclone plugin deadlocks under concurrent restores and fsync is not durable on a `full` cache.
- An image wrapper or entrypoint script for the guard: the image is distroless and custom images need explicit approval; the bind-mount guard achieves the same refusal natively.

## Consequences

- Loki depends on frost-fang's disk again; durability comes from the GCS backup (disaster recovery) and the warm copy (failover with RPO of minutes).
- The marker must be created whenever a store is restored on a new node; forgetting it fails closed.
- The in-memory chunks are written on shutdown (`flush_on_shutdown`, 2 minute grace period); an unclean kill leaves the WAL, which the replica copy also carries.

## Rollback

Restore the committed previous `loki.yml` and `logging.yml` (GCS-primary, commit 418c4b8), redeploy `loki` with `--bump-config`. The GCS data under `loki/cluster/data/` is intact, and the Loki identity and secret remain.

## Verification

See the counts above; `docker inspect` on the task shows the two bind mounts; `rclone lsf` shows no new Loki writes to `loki/cluster/data/` after the cutover; the log-rate and backup alert rules stay healthy.
