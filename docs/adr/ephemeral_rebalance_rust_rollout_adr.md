# ADR: ephemeral-rebalance Rust controller rollout

Date: 2026-10-12. Status: accepted; deployed in dry-run, apply mode pending verification.

## Context

`main-maintenance_ephemeral-rebalance` ran a mounted shell script in a Docker CLI image. On
2026-10-11 it force-updated every rejected service roughly every 45 seconds while the rclone
volume driver timed out on every node, and it was scaled to 0 as a stopgap. Its replacement is
the reviewed Rust controller (the ephemeral-rebalance project, `v0.2.0`), which adds a systemic-failure
breaker, a cluster-wide update budget, optional node-health gating and staged, convergence-paced
node-driven rebalances. This repository is public, so private registry and project identifiers
belong in operator configuration, not in source history.

## Decision

- Set `EPHEMERAL_REBALANCE_IMAGE` in the untracked operator environment to the approved
  digest-qualified image reference; the compose file requires it and has no floating fallback.
  The first released artifact is `v0.2.0`, digest
  `sha256:fd39a4c891e22d70011f48a95fc8c7011a3be3b59d9d1f5c247cdefd6b64fd61`.
- Run `run` as uid 65532 with the Docker socket group (default 998,
  `EPHEMERAL_REBALANCE_DOCKER_GID`) as the primary group: `docker stack deploy` rejects
  `group_add`. Read-only rootfs, all capabilities dropped, 0.25 CPU, 128 MiB, 64 PIDs, 16 MiB
  reservation, one Tokio worker, stop-first updates with rollback on failure.
- Keep the existing approved placement label `node.labels.swarm.leader == true`; no hostname or
  node-ID placement and no new labels.
- Use a new local state volume `main-maintenance_ephemeral-rebalance-rs-state`; the legacy state
  volume and script config stay untouched so the rollback is exact.
- Start with `EPHEMERAL_REBALANCE_APPLY=false` (dry-run shadow). Switch to apply only after the
  shadow output is verified, then verify node leave/rejoin with a planned restart of the
  ephemeral node while its owner is not using it.
- The image was built on a cluster node from the signed release tag and published with the
  operator's existing identity through a short-lived token on stdin; nodes pull by digest through
  the same operator-mediated path (automatic private cold pull is not implemented, as for
  rclone-fixer).

## Alternatives

- Keep the shell controller: rejected; it has no cluster-wide limit and caused the 2026-10-11 storm.
- `group_add` for socket access: rejected by the stack schema.
- Run as root: unnecessary once the socket group is the primary group.
- Reuse the legacy state volume after `chown`: rejected to keep rollback exact and avoid mutating
  production state.

## Rollback and verification

Immediate rollback is `docker service rollback main-maintenance_ephemeral-rebalance` (previous
spec: legacy script at 0 replicas); the source rollback restores the prior service block and
redeploys through `cluster-utils deploy service`. Verification covers the running digest, user,
limits, restarts and the controller log, not only the replica count. Private evidence stays in
the untracked operator report.

## Temporary database-availability hold, 2026-10-12

The deployed controller was already changed to dry-run during an incident, but
the operator environment still enabled apply mode. A later service reconciliation
could therefore silently re-enable forced updates before the incident was closed.

The operator environment now explicitly sets `EPHEMERAL_REBALANCE_APPLY=false`,
and the service retains its templated `REBALANCE_APPLY` setting. This is a
temporary operational hold, not retirement of the controller. The process, state
volume, image, resource bounds, placement and observation paths remain unchanged.
The hold is reconciled through `cluster-utils deploy service ephemeral-rebalance`
after Compose and Swarm render checks. It makes the source match the observed
emergency runtime state without changing database data or restarting a daemon.

The incident correlated repeated task replacement and host I/O/heartbeat pressure
with database-pool outages. A concurrent compilation workload may add pressure,
but its start was later than some outages and it is not established as the sole
cause. The hold must be verified by unchanged critical task generations and real
application database transactions, not merely by a running controller container.

Resume only after the owning workflow verifies pressure gating, bounded replay
and adequate capacity. Deliberately choose the operator apply value, render,
and reconcile the same service through `cluster-utils`. Preserve the state volume
and inspect any interrupted round before resuming it. Do not use a broad stack
rollback over concurrent changes.

Private dated runtime evidence and offline-node coverage are retained in the
operational incident report rather than in this public configuration decision.
