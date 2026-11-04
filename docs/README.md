# Cluster documentation

## Speech and model serving

- [STT runtime and credential decision](adr/cluster_stt_adr.md): official serving runtime, LiteLLM alias, exact-path custody, acceptance gates and rollback.

## Placement and operations

- [Node labels](node-labels.md): approved placement groups.
- [GPU monitoring](gpu-monitoring.md): GPU observations.
- [Naming standards](naming-standards.md): cluster naming conventions.
- [Messaging](messaging.md): messaging services.

## Game server backups

- [Pterodactyl GCS backup proposal](adr/pterodactyl_gcs_backup_proposal_adr.md): proposed identity, staging, restore verification and rollback gates.

## Capacity and scheduling decisions

- [Memory and swap budgeting](adr/2026-10-11-memory-swap-budgeting.md): every memory budget states its swap budget.
- [Node-local state pinning](adr/node_local_state_pinning_adr.md): which volumes are node-local and how consumers are pinned.
- [Ephemeral rebalance Rust rollout](adr/ephemeral_rebalance_rust_rollout_adr.md): controller rollout and gates.
- [Redis database IDs](redis-db-ids.md): per-service Redis database allocation.

## Configuration and secrets

- [Environment-variable contract](adr/env_contract_adr.md): typed contract in `config/env-contract.yaml`, `scripts/env_contract.py` (tests in `tests/test_env_contract.py`), the layered shell-script `.env`, and why encrypted-secrets tooling was deferred.

## Observability and identity

- [Grafana managed ingress alert routing](adr/grafana_managed_ingress_alert_routing_adr.md): alert routing for managed ingress.
- [Authelia backup direct discovery](adr/authelia_backup_direct_discovery_adr.md): how the backup finds its target.

## Examples

Review-only compose fragments in [examples/](examples/): Pterodactyl DB rotation, panel v1 upgrade overlay, Wings GCS backup volume and native GCS S3 settings. Merge them into the reconciled live stack; never deploy them alone.
