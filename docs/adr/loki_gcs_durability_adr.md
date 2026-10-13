# ADR: Loki log durability through scheduled GCS archives

Date: 2026-10-13 06:40 UTC

## Context

Loki 3.6.4 stores chunks and its TSDB index on the node-local Docker volume `main-logging_loki-data` (driver `local`). On 2026-10-13 it held about 2.0 GiB in roughly 9,800 chunk files with 7 day retention (`compactor.retention_enabled`, `LOKI_RETENTION_PERIOD=168h`). Nothing copied it elsewhere. The volume lives on frost-fang, the node with chronic I/O stalls (PSI `some` avg60 between 15 and 60 on 2026-10-13), and Loki's placement is only `swarm.leader != true`, so a reschedule to another node would start with an empty volume.

The preferred outcome was Loki writing chunks natively to the shared artifact bucket under `loki/<slug>/` (Santiago, Standard, versioning on, 7 day soft delete).

## Findings on native GCS

- The bucket exists and is writable by the operator account. The cluster credential `swarm-storage-worker` has `roles/storage.objectUser` on the whole bucket and reaches the nodes as a plugin-private key file for the rclone Docker volume driver.
- Loki's GCS client needs a credential inside the Loki container. The only cluster credential is the broad `swarm-storage-worker` key (read, write and delete on every prefix, including the Restic workspace backups). Placing it in a Docker secret would give an internet-fed log parser a key that can delete other projects' data, and would add a second static copy of a service-account key. The `gcp-workload-identity-iac` policy excludes new static keys, and the Swarm nodes have no workload identity yet (the Keycloak `gcp-workload-federation` realm is dormant behind its production gates).
- Running Loki's chunk directory on an rclone FUSE volume was rejected: the plugin has a documented deadlock (`rclone docker plugin 1.75 deadlock on concurrent volume restore`), and `fsync` on an rclone `vfs_cache_mode=full` mount is not durable on GCS, the mechanism behind the Portainer BoltDB corruption.

## Decision

1. Keep Loki's primary store on the local volume (no change to ingestion).
2. Add `main-logging_loki-backup`: an official `rclone/rclone` image running busybox `crond`. It archives `chunks`, `index` and `compactor` (excluding the WAL and caches) twice a day (02:30 and 14:30 UTC) into the rclone volume `loki-backups`, remote `gcs:<artifacts bucket>/loki/cluster/backup`. Archives are write-once tar files, a workload the rclone `full` cache handles well. Six archives are kept; bucket versioning and soft delete add 7 more days.
3. The job is I/O-gated: it waits (bounded to 90 minutes, then fails) until host `some avg60` is at most 75, runs `tar` under `nice -n 19 ionice -c3` with 0.5 CPU and 256 MiB limits, refuses to archive a source that lacks `chunks` and `index` or holds less than 1 MiB, publishes by atomic rename after listing the archive, and writes Prometheus textfile metrics (`loki_backup_last_success_timestamp_seconds` and others). A Grafana rule alerts when no success has occurred for 36 hours.
4. Prepare the native GCS path without applying it. Once a dedicated, prefix-scoped identity exists, add a second `schema_config` period with a future `from` date and `object_store: gcs` while keeping the filesystem period readable. The required IaC (service account, managed folder `loki/cluster/`, `objectUser` on that folder) belongs in `FarDust/personal-stack-infrastructure` through its Terraform Cloud gates and is not applied by this change.

## Alternatives

- Native GCS with `swarm-storage-worker` in a Docker secret: rejected above (blast radius, static key copy).
- Dedicated service account key from IaC: needs a Terraform Cloud plan, apply and a static key; deferred to the follow-up.
- Chunks on an rclone FUSE volume: rejected above.
- Bucket lifecycle rules: not applied. Lifecycle or retention changes on the shared bucket need explicit approval, so pruning happens in the job.
- Keep only the local volume: leaves a single copy on the least stable node.

## Cost

Each archive is about 2 GiB. Six retained archives plus soft delete is roughly 12 to 24 GiB of Standard storage in Santiago (a few tenths of a USD per month at Standard rates). Writes are ingress and free of egress; reads happen only on restore. Class A operations are a handful per archive (resumable upload parts), a few hundred per month. Two archives per day is the compromise between recovery point and I/O load on a stalled node.

## Consequences

- Recovery point objective is up to 12 hours.
- Archives taken while Loki runs are crash-consistent, not transactionally consistent. The last minutes of chunks referenced by the index may be absent after a restore, which Loki tolerates.
- The job proves the archive was written to the FUSE mount and is a well-formed tar. Confirmation that the object reached GCS comes from `gcloud storage ls` on the prefix (the container holds no credential), recorded in the dated report.
- A reschedule of Loki to another node would still start from an empty volume. A durable placement rule (for example `load.tier == heavy`) is a separate change.

## Restore procedure

1. Stop Loki: `docker service scale main-logging_loki=0`.
2. Copy the newest `loki-*.tar` from `gs://<bucket>/loki/cluster/backup/` to the node (or read it from a `loki-backups` mount), extract it into the empty target volume with `loki-backup.sh restore <archive> <target>` or `tar -xf`.
3. Start Loki, check `/ready`, then query a time range inside the archive.

## Verification

The dated report records the object listing and sizes, the MD5 comparison of the uploaded archive with a recomputed value, and a restore into a scratch directory read by a throwaway Loki instance.
