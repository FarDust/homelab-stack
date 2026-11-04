# Loki is pinned to the storage-manager nodes

Date: 2026-10-13 16:10 UTC

## Context

`main-logging_loki` keeps chunks, the TSDB index and the WAL on the node-local volume `main-logging_loki-data`. Its only placement constraint was `node.labels.swarm.leader != true`. After gabriel-pc-wsl rejoined at 06:21 UTC on 2026-10-13, ephemeral-rebalance moved Loki there (task `qit5e4lv4qfz`, started about 07:13 UTC). The WSL node held an old, unrelated `main-logging_loki-data` volume (765 MB, files from February to that day), so Loki ran against a different dataset for about nine hours. The 2 GB of history on frost-fang stopped receiving writes at 07:13 UTC and was unreachable from Grafana. The backup job (frost-fang only) kept archiving the frost-fang volume, so no archive was lost.

## Decision

Add `node.labels.storage.manager == true` to the Loki constraints (applied live 2026-10-13 16:05 UTC with `docker service update --constraint-add`, then persisted in `stacks/main/logging.yml`). With `swarm.leader != true` this selects frost-fang. ephemeral-rebalance already skips services pinned by a cluster-group constraint (same mechanism as `docs/adr/keycloak_pinned_placement_adr.md`). The change is label-based; no hostname pin.

Before the move, the WSL volume was archived to `gs://<artifacts-bucket>/loki/cluster/backup-wsl/loki-20261013T155854Z.tar` (746,264,064 bytes, md5 `97ce94cdd5249fa821f8362a3677667e`, equal on the GCS side). The WSL volume itself is untouched.

## Alternatives

- Teach the controller a protected-service list by name: rejected; movement rules are label-driven.
- Keep it movable and rely on the backup job refusing empty volumes: rejected; the job runs on a different task and cannot stop Loki itself from starting empty.
- Move the storage to GCS so no node matters: decided separately (stage 2); this pin stays until Loki's chunks and index are object-store backed.

## Consequences

- If no storage-manager node other than the leader is Ready, Loki stays unscheduled instead of starting empty.
- Logs written on WSL between 07:13 and 16:05 UTC are not in the frost-fang store; they are recoverable from the archive above and are merged during the GCS migration.

## Verification

After the update, Loki ran on frost-fang, and 2026-10-12 12:00-13:00 UTC counts through Grafana matched the earlier values (postgres 428000, traefik 9199, loki 790).
