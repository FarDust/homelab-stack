# Firefly III upload backup placement and Firefly pin

Date: 2026-10-13

## Context

`firefly_iii_upload` is a node-local Docker volume (stack-scoped `productivity-finance_firefly_iii_upload`). `fireflyiii` ran on the storage-manager node while `firefly-upload-backup` was constrained to the ephemeral GPU node (the desktop worker), so the backup mounted a different, empty copy of the volume and its archive could never contain what the application stored. The audit in `node_local_state_pinning_adr.md` found 0 files on both copies, so nothing was lost, but the backup could not see real uploads.

At about 15:15 Chile on 2026-10-13, `productivity-finance_fireflyiii` was changed live to add `node.labels.storage.manager == true` and a 3 CPU limit (to speed up finance writes). The Firefly database is PostgreSQL; only the upload volume is node-local.

## Decision

1. `fireflyiii` and `firefly-upload-backup` share one placement anchor, `x-firefly-placement`, in `stacks/productivity/finance.yml`: worker, home site, metal, heavy tier and `node.labels.storage.manager == true`. The backup therefore lands on the node that runs Firefly and mounts the same local volume; the label pin matches the live Firefly constraint.
2. The backup keeps its rclone volume (`backups/fireflyiii-upload` in the shared bucket, node independent) and its local restore-probe volume; both work on any node.
3. The persisted Firefly CPU limit is 2 CPUs (the file said 1.0, live is 3). The coordinator applies it live after the finance writes finish; this change only persists it.

## Alternatives

- Move the upload volume to rclone/GCS like the backup target: higher latency for uploads and a data migration; deferred.
- Keep the backup on the ephemeral node and copy the volume over the network: more moving parts than co-locating.
- Hostname pin: rejected by cluster rules.

## Consequences

- Both services fail to schedule if no storage-manager worker is Ready.
- Until deployed, the running backup still targets the empty WSL copy.
- Redeploying `fireflyiii` restarts a finance application; deploy only after the finance writes finish.

## Verification

`docker stack config -c stacks/productivity/finance.yml` renders both services with the five constraints including the storage-manager label, and `fireflyiii` with `cpus: "2.0"`. Nothing was applied live. Post-deploy check: the backup task runs on the storage-manager node and its receipt reports a `source_file_count` equal to the file count of `productivity-finance_firefly_iii_upload` there.
