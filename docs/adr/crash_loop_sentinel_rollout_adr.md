# ADR: Crash-loop sentinel rollout

Status: accepted (2026-10-13). Source of truth for the behaviour: `FarDust/crash-loop-sentinel`,
`docs/adr/shed_sentinel_adr.md`.

## Context

The 2026-10-12 frost-fang incident showed a service (Infinity) writing about 900,000 log lines in
three hours across 11 restarts without anyone noticing, and the response (scaling services to zero)
destroyed evidence. Grafana now alerts on task churn and log rate
(`workload_churn_log_storm_alerts_adr.md`); alerts do not act. The sentinel is the action half and
acts only on services that opt in.

## Decision

- Service `crash-loop-sentinel` in `stacks/main/maintenance.yml`, one replica pinned to the
  swarm-leader label, user `65532:<docker gid>`, read-only root, all capabilities dropped, limits
  0.15 CPU, 48 MB, 32 pids, stop-first with rollback.
- Image: digest-qualified private Artifact Registry reference in `.env` (`SENTINEL_IMAGE`).
- **Observe by default.** `SENTINEL_APPLY=false` in `.env`. In observe mode the whole pipeline runs and
  sends `SentinelWouldShed`, but nothing is scaled. Apply mode needs `SENTINEL_APPLY=true` and a
  deploy, exactly like `EPHEMERAL_REBALANCE_APPLY`.
- **No service is opted in by this change.** Opt-in is the service label `sentinel.shed=true`; the
  sentinel refuses databases, identity, Traefik, monitoring and logging, backups, the controllers
  and itself even when labelled (list in the repository ADR).
- Networks: `traefik` (Loki `loki:3100`, Alertmanager `alertmanager:9093`) and `prometheus`
  (`tasks.prometheus:9090`, stats snapshot only).
- Evidence: bundles are written to the local volume `main-maintenance_crash-loop-sentinel-evidence`
  and mirrored (required) to the rclone volume `crash-loop-sentinel-evidence-gcs`, remote
  `gcs:${ARTIFACTS_GCS_BUCKET}/sentinel/evidence`, in the shared artifact bucket. If the mirror
  cannot be written the capture fails and the sentinel does nothing.
- Notifications reach the existing Alertmanager receiver (`routine-n8n`) with `tier=maintenance`.

## Opt in, restore, roll back

- Opt in: `docker service update --label-add sentinel.shed=true <service>`; opt out: remove the label.
- Restore a shed service: `docker exec <sentinel container> /crash-loop-sentinel restore <service> --apply`,
  or `docker service update --label-add sentinel.restore=true <service>` (apply mode). The previous
  replica count is on the service as `sentinel.shed.previous-replicas`.
- Stop all action: set `SENTINEL_APPLY=false` and run `cluster-utils deploy service crash-loop-sentinel`.
- Remove: scale to 0 or delete the stanza and the three volumes; shed services keep their labels and
  can still be restored with `docker service scale` plus label cleanup.

## Consequences

- One more privileged (Docker socket) service on the manager. It is small, read-only and starts in
  observe mode.
- Evidence capture depends on the rclone plugin for the mirror; a wedged plugin makes captures fail
  closed instead of shedding without a backup.
