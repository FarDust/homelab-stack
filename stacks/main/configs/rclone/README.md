# Legacy rclone fixer (`check.sh`)

The current **rclone-fixer** service runs the Rust controller, not `check.sh`. See the
[rollout and rollback ADR](../../../../docs/adr/rclone_fixer_rust_rollout_adr.md).

This directory retains `check.sh`, `check.test.sh`, the unused `rclone-fix-script`
config declaration and their CI coverage as rollback assets. They are not mounted or
executed by the current Rust service. Use them only through an approved rollback and
keep one recovery controller per daemon. The sections below describe the legacy script.

The legacy script probes the rclone volume plugin and can optionally disable/enable it
or reconcile stale mount directories when Docker metadata and plugin state disagree.

Compose: [`maintenance.yml`](../../maintenance.yml) → service `rclone-fixer` (stack `main-maintenance`).

## Legacy Docker Swarm behaviour

### Deployment model

- **`deploy.mode: global`** — one task per Linux node (managers and workers).
- Each task uses **only the local engine** via `/var/run/docker.sock` on **that** host.

### APIs the script uses (worker-safe)

These commands work on **every** swarm node through the local daemon:

| Area | Commands |
|------|----------|
| Plugin | `docker plugin inspect`, `docker plugin enable` / `disable` |
| Volumes | `docker volume create` / `rm` / `inspect` (probe + recreate) |
| Stale spec | `docker ps -aq --filter volume=…`, `docker inspect` (containers) |

The script **does not** call Swarm control-plane CLIs (`docker service`, `docker node`, `docker swarm`, `docker stack`). Those are **manager-oriented** and are a poor fit for a **global** sidecar that must behave the same on workers.

### Stale mount reconciliation

When the rclone plugin leaves a **non-empty** path under its propagated-mount area but **`docker volume inspect`** says the volume does not exist, the fixer can recreate the volume **if** it can recover **driver name + driver options**.

**Source of truth on each node:** mounts from **local containers** that reference that volume name:

1. `docker ps -aq --filter volume=<volume_name>`
2. `docker inspect` → `HostConfig.Mounts[]` → `VolumeOptions.DriverConfig` (same shape as in compose/swarm service definitions)

So workers do not need `docker service inspect`; they only need containers/tasks scheduled on **that** node that still reference the volume (running or exited — `docker ps -a`).

**Limits:**

- If **no** local container references the volume anymore, the spec cannot be recovered on that node; the script logs a warning and skips.
- Plugin paths must match the task environment (see env vars below). On the host, override `RCLONE_STALE_PLUGIN_BASE` and `STATE_FILE` when running `check.sh` manually.

### Related maintenance services

[`ephemeral-rebalance.sh`](../maintenance/ephemeral-rebalance.sh) **does** use `docker service` / `docker node` and is pinned to the **swarm leader** in compose. That is intentional; it is not the same execution model as rclone-fixer.

## Legacy configuration (environment)

| Variable | Default | Role |
|----------|---------|------|
| `RCLONE_FIX_ENABLED` | `false` | Must be `true` or the script exits immediately |
| `RCLONE_FIX_INTERVAL` | `60` | Seconds between loop iterations |
| `RCLONE_FIX_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARN` \| `ERROR` |
| `RCLONE_PLUGIN_NAME` | `rclone` | Plugin name for inspect/probe |
| `RCLONE_STALE_REPAIR_ENABLED` | `true` | Enable stale propagated-mount reconciliation |
| `RCLONE_STALE_PLUGIN_BASE` | `/host-plugins` | Legacy plugin-root bind described below |
| `STATE_FILE` | `/state/docker-plugin.state` | Rclone plugin state file (cache mount in compose) |
| `RCLONE_PROBE_TYPE` | `local` | Probe volume option `type` (interpreted on host by the plugin) |
| `RCLONE_PROBE_PATH` | `/tmp` | Probe volume option `path` |

## Legacy Compose volume mounts (reference)

Historical mounts for `check.sh`, not the current Rust service declaration:

- `/var/run/docker.sock` — local engine API
- `/var/lib/docker-plugins/rclone/cache/` → `/state/` — writable legacy plugin cache / state
- `/var/lib/docker/plugins` → `/host-plugins` — plugin install tree (for propagated-mount path)

## Tests

[`check.test.sh`](./check.test.sh) covers `create_volume_from_spec` (shell safety and argv building). CI: `.github/workflows/check-main-maintenance.yml`.

These tests preserve the rollback implementation; they do not validate the Rust binary.
