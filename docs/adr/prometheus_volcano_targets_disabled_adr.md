# Disable the Volcano Prometheus scrape jobs

- Status: accepted 2026-11-06 (owner decision)

## Context

The `main-traefik_prometheus` service mounts the swarm config `prometheus_volcano_target` at `/etc/prometheus/targets/volcano_target.yaml`. The `volcano-scheduler` and `volcano-controllers` jobs in `stacks/main/configs/prometheus/prometheus.yml` read it and probed the Volcano endpoints on port 8443 roughly every 25 seconds. The Kubernetes cluster is retired and never served them, so every probe failed and produced about 3,000 firewall BLOCK log lines per day.

## Decision

Comment out the two Volcano scrape jobs in `prometheus.yml` (kept in place, not deleted). The untracked `volcano_target.yaml` file (git-ignored) and the config mount in `stacks/main/traefik.yml` stay as they are, so the stack still renders. Grafana Volcano dashboards and the k3s manifests under `clusters/main/k3s` are untouched.

## Alternatives

- **Empty the targets file only:** rejected. The file is git-ignored, so the change would not be reviewable in the repository.
- **Delete the jobs:** rejected. Re-enabling should be an uncomment, not a rewrite.

## Consequences

Prometheus stops probing the retired endpoints once the main stack is redeployed. Volcano panels and any alerts depending on Volcano series go empty. To re-enable, uncomment both jobs and redeploy.

## Verification

`promtool check config` passes (CI job `check-main-monitoring`). After deploy, the `volcano-*` jobs no longer appear under Prometheus targets and the BLOCK lines stop.

## Deployment

Not deployed by this change. The config is versioned by `CONFIG_VERSION` (`prometheus_config-${CONFIG_VERSION:-0}`), so deploying requires bumping `CONFIG_VERSION`, then `source .env` and redeploying the `main` stack with the repository's normal deploy command. Wait until the Swarm manager is stable first, never drain nodes and do not restart daemons.
