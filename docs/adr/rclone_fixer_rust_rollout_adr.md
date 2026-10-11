# ADR: Scoped Rust recovery controller rollout

Date: 2026-10-11. Status: accepted and deployed on the two Ready Linux/x86_64 nodes.

## Context

The previous service ran a Docker CLI image and a mounted shell script. The reviewed
replacement is a static Rust controller with explicit apply/scope gates, durable cooldowns,
bounded requests and observable failure states. This repository is public, so private
registry/project identifiers belong in operator configuration rather than source history.

## Decision

Set `RCLONE_CONTROLLER_IMAGE` in the untracked operator environment to the approved
digest-qualified image reference. The compose file requires that variable and has no
floating or public fallback. The initially verified artifact digest is
`sha256:31da1a2e04c24a960e93b16e0532dfd37d3baf76b763e30e65ce9f9fac343a1b`.
Parameterizing the source must preserve the resolved live service exactly; no runtime
redeploy is needed merely to remove a private registry identifier from tracked source.

Compose interpolation enforces presence, not digest syntax. The example environment is
render-only; the operator must supply and verify the approved digest before deployment.

Run `--apply watch` with these actual CLI environment keys:

- `RCLONE_FIX_ENABLED=true`
- `RCLONE_FIX_INTERVAL=60`
- `RCLONE_FIX_LOG_LEVEL=info`
- `RCLONE_EXPECTED_NODE_ID={{.Node.ID}}`
- `RCLONE_ALLOWED_PLUGIN_REFERENCES=docker.io/rclone/docker-volume-rclone:amd64-1.75.2`
- `TOKIO_WORKER_THREADS=1`

Swarm expands the node template in the environment, not argv. The node binding validates
the local socket's identity; it is not a placement pin. Use global Linux/x86_64 platform
guards and no hostname/node-ID targeting or new labels.

Retain the local Docker socket, make the existing plugin cache/state bind read-only,
and add the metrics bind. Remove the unused writable plugin-install-tree bind.
Verify `/var/lib/node_exporter/textfile_collector` exists on every eligible future node
before scheduling, along with the required socket and cache paths.
Use a separate persistent local journal
volume per daemon. Enforce read-only rootfs, dropped capabilities, 64 MiB, 0.10 CPU,
32 PIDs and an 8 MiB reservation. Use stop-first updates/rollback, a 60 s monitor window
and bounded restart attempts. SYS_ADMIN/FUSE remain exclusively with the managed plugin.

Access to the host Docker socket is root-equivalent, as it was for the legacy service.
Dropping Linux capabilities and using a read-only rootfs do not neutralize that daemon
authority; this is a trusted host controller, not a least-privilege sandbox.

## Publication and alternatives

The initial release reused the verified rootless build and approved operator credentials
to publish and pre-pull the immutable private artifact, avoiding compilation on pressured
nodes. No new static credentials, IAM grant, registry proxy or credential service was added.
An automatic WIF/private cold-pull mechanism is not implemented; a new or uncached node
must use the approved pull path before scheduling can succeed. Cache residency is not
claimed as autonomous bootstrap availability.

Keeping the old shell controller was the exercised rollback, not the selected final
runtime. Retain `check.sh`, `check.test.sh`, the unused `rclone-fix-script` declaration
and `.github/workflows/check-main-maintenance.yml` to preserve that rollback option and
its shell regression coverage. The Rust service mounts neither the script config nor
the legacy plugin-install-tree bind. Those assets are not a second active controller.
Weakening scope validation, using a hostname workaround, disabling storage-aware
healthchecks or moving backup workloads were rejected as ways to manufacture success.

## Rollback and verification

Preserve the previous exact image/config and focused source snapshot privately. Restore
only the fixer service and owned journal definition, preserving concurrent sibling work;
render, validate and redeploy through the canonical single-service workflow. Retain the
journal and all application data. No daemon/node restart, drain or volume deletion is
part of rollback.

Verify the actual running digest, expanded node identity, limits, logs and subsequent
cycles beyond the update window, not merely a transient replica count. Controller process
health and backend/backup health are separate claims. The deployment and read-only Ollama
findings are recorded in the [public rollout receipt](../reports/rclone_fixer_rust_rollout_20261011.md).
Private raw evidence and infrastructure identifiers remain in the operator's untracked
canonical report, rather than being copied into this public record.
