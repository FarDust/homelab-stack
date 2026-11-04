# Authelia backup uses direct task discovery

Status: accepted for scoped deployment, 2026-10-12 19:20 UTC.

## Context

The maintenance investigation found the same address/MAC on the backup node's load-balancer
endpoint and the manager Authelia Redis task in main-traefik_authelia-db. The backup
worker runs on that node and its service-VIP traffic traverses that colliding source.
Existing backups remain recoverable, but a live configured-endpoint test passed
two 20-second read-only transactions then hung beyond 45 seconds. The owned hung
diagnostic psql process was terminated without touching the scheduler.

The same running backup container, credentials, database and SQL passed three
20-second transactions against tasks.authelia-db. This isolates the failing VIP
path from credentials, database readiness and database execution. No production
data was written by these controls.

## Decision

Set only authelia-db-backup POSTGRES_HOST to tasks.authelia-db in
stacks/main/maintenance.yml. Docker's embedded DNS supplies the current task
addresses without the VIP/SNAT path. Keep the single database replica, network,
port, credentials, TLS setting, volumes, schedule and placement unchanged.
Render and deploy only that backup service through cluster-utils.

This is a scoped avoidance of a reproduced broken load-balancer path, not a repair
of Swarm IPAM or proof that other duplicate addresses cannot recur. The existing
overlay owner retains that broader defect. No Redis recreation or session loss
is required for this backup change.

## Alternatives

- Recreate volatile Authelia Redis: may clear the collision but invalidates current
  sessions; rejected in favor of a narrower backup-only change.
- Hard-code a task IP: would break on task replacement; rejected.
- Recreate networks/restart Docker/drain nodes: broader disruptive recovery outside
  this scoped fix; not performed.
- Leave the VIP unchanged because a short query passed: contradicted by the long
  transaction timeout; rejected.

## Consequences

Each backup connection resolves task DNS at connection time. A task replacement
can still interrupt an active dump, which must remain a reported failed backup.
The fail-closed backup runner, timeout, publication checks and schedule remain
responsible for that behavior. Direct discovery is appropriate here for a single
PostgreSQL task; it is not a writable-primary selection mechanism for replicas.

## Verification and rollback

Before change: VIP 2 passes followed by one 45-second timeout; direct task route
3/3 passes from the same backup runtime. After deploy require the exact live
POSTGRES_HOST, successful authenticated transaction, backup runner execution,
independent object publication/readback and isolated recovery of the new artifact.
Preserve other jobs and Redis task identities.

Rollback only the changed POSTGRES_HOST line to authelia-db, validate the render,
and run cluster-utils deploy service authelia-db-backup --compose-file
stacks/main/maintenance.yml --stack-name main-maintenance --timeout 300. Recheck
the service and report that rollback reintroduces the observed route risk.
Do not restore a whole older file over concurrent changes.

Source: https://docs.docker.com/engine/swarm/networking/#container-discovery
retrieved 2026-10-12; explicitly documents tasks.<service-name> resolution.
Context7 was unavailable because its monthly quota was exhausted.

## Deployment receipt, 2026-10-12 20:00 UTC

The first canonical deployment at 19:21 returned partial exit 12 and rolled back
during an existing rclone deadlock. After its separately owned patched
plugin canary, one bounded retry at 19:46 reached 1/1 with the intended host.
At 19:58 the current backup task produced both 12-October archives through the
direct route. Independent GCS readback matched both mounted checksums, and an
isolated PG14 restore recovered 25 Authelia tables; cleanup passed. Exact runtime
evidence and the separate host-churn residual are retained in the private
operational report, not published with this decision. Redis sessions and
production data were kept.
