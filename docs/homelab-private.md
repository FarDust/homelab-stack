# Private deployment directory (`HOMELAB_PRIVATE_DIR`)

This repository is public and doubles as a template. Everything that identifies one deployment (real domain, host names,
bucket names, database access rules, dashboards rendered for that cluster, backup tooling tuned to its volumes) lives in a
separate private repository. Stacks reach it through one required variable:

```sh
export HOMELAB_PRIVATE_DIR=/path/to/private-deployment-repo   # checkout of your private repository
```

`HOMELAB_PRIVATE_DIR` is a `${VAR:?message}` or `${VAR?err}` interpolation, so a stack that needs a private file fails at
render and deploy time with a message naming the variable when it is unset. The variable is part of the environment contract
(`config/env-contract.yaml`, owner `main/storage`; see [the contract ADR](adr/env_contract_adr.md)). Relative paths inside
the private repository mirror this repository's layout.

Keep hyphens out of the message of a `${VAR:?message}`: `docker stack deploy` reads the first hyphen as the default operator and
resolves the expression to the text after it (see [the ADR](adr/swarm_interpolation_required_message_adr.md)).

## Files each stack expects

| Stack | File under `${HOMELAB_PRIVATE_DIR}` | What it must do | Template |
| --- | --- | --- | --- |
| `main/storage` | `stacks/main/configs/supabase/pg_hba.conf` | PostgreSQL host-based authentication for the Supabase database; mounted as a Swarm config at `/etc/postgresql/pg_hba.conf`. | `examples/homelab-private/stacks/main/configs/supabase/pg_hba.conf.example` |
| `main/storage` | `stacks/main/configs/supabase/postgresql-custom-overrides.conf` | Cluster-specific PostgreSQL settings; mounted at `/etc/postgresql-custom/custom-overrides.conf`. May be empty. | `.../supabase/postgresql-custom-overrides.conf.example` |
| `productivity/finance` | `stacks/productivity/configs/finance/actual-data-backup.sh` | `/bin/sh` script run once by the dormant `actual-data-backup` service: archive `/source` (read-only Actual data) into `/backups`, restore it into `/restore`, compare checksums and exit non-zero on any mismatch. | `.../finance/actual-data-backup.sh.example` |
| `productivity/finance` | `stacks/productivity/configs/finance/firefly-upload-backup.sh` | `/bin/sh` script run by the `firefly-upload-backup` service: same backup and restore probe for `/source` (Firefly uploads), then create `/run/firefly-upload-backup-ready` (the healthcheck) and keep running. | `.../finance/firefly-upload-backup.sh.example` |
| `main/traefik` (Grafana) | `grafana-dashboards/dist/<name>.json` for `cluster-operations-overview`, `ingress-reliability`, `swarm-workload-pressure`, `swarm-service-detail`, `observability-pipeline-health` | Rendered Grafana dashboard JSON whose `uid` equals the file name and that has at least one panel. Provisioned as Swarm configs scoped by `GRAFANA_CONFIG_VERSION`. | `examples/homelab-private/grafana-dashboards/dist/*.json` (one placeholder panel each) |
| `main/traefik` (Prometheus) | `stacks/main/configs/prometheus/ingress_blackbox_targets.yaml` | Prometheus `file_sd` targets for the ingress control-plane probes (`monitor_group: ingress_control_plane`) using your real domain; the alerts in `alert.rules` and the Grafana alerting rules read those labels. | `.../prometheus/ingress_blackbox_targets.yaml.example` |

The templates live under [`examples/homelab-private/`](../examples/homelab-private/). Copy the tree into your private
repository, drop the `.example` suffix and adapt each file. The dashboard placeholders already satisfy the checks, so a newcomer
can deploy the stack with `cp -r examples/homelab-private/grafana-dashboards "$HOMELAB_PRIVATE_DIR/"` and replace them later.

## Dashboards

The five rendered dashboards are built by a separate private dashboards-as-code repository. Check it out (or add it as a
git submodule of the private repository) at `${HOMELAB_PRIVATE_DIR}/grafana-dashboards`, so that its `dist/` directory holds the
JSON files above. Without that directory the Grafana configs have no source file and `docker stack deploy` fails on the missing
path; with the placeholders from `examples/` the stack deploys with one text panel per dashboard.

Config versioning is unchanged: every dashboard config name carries `GRAFANA_CONFIG_VERSION`; after changing a dashboard in
the private checkout run `scripts/grafana-config-version.sh bump` and redeploy. `scripts/tests/test-grafana-config-version.sh`
validates the compose wiring and the JSON artifacts, using `${HOMELAB_PRIVATE_DIR}/grafana-dashboards` when it exists and the
placeholders otherwise.

## Keeping this repository generic

- Put the real domain, host names and private repository names only in the private repository or in the environment
  (`DOMAIN_NAME`, `LOCAL_DOMAIN`, ...). Documentation uses `example.com` or `${DOMAIN_NAME}`.
- Supporting reports, receipts and rollback copies stay in the private deployment records; ADRs say so instead of linking paths
  that do not exist here.
- `scripts/check_private_indicators.py pre-commit` guards each commit and `scripts/check_private_indicators.py scan-tree` runs the
  generic subset over the whole tree in CI (see [the guard ADR](adr/private_indicator_guard_adr.md)). Your own domain belongs
  in the untracked deny-list `.git/private-indicators.txt`.
