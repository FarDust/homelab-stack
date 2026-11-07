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
- [Wings game-container host prerequisites](adr/wings_container_host_prerequisites_adr.md): machine-id bind source and container DNS for game servers.

## Capacity and scheduling decisions

- [Memory and swap budgeting](adr/2026-10-11-memory-swap-budgeting.md): every memory budget states its swap budget.
- [Node-local state pinning](adr/node_local_state_pinning_adr.md): which volumes are node-local and how consumers are pinned.
- [Ephemeral rebalance Rust rollout](adr/ephemeral_rebalance_rust_rollout_adr.md): controller rollout and gates.
- [Redis database IDs](redis-db-ids.md): per-service Redis database allocation.

## Configuration and secrets

- [Private deployment directory](homelab-private.md): `HOMELAB_PRIVATE_DIR`, the files each stack expects there, and the templates in `examples/homelab-private/`.
- [Environment-variable contract](adr/env_contract_adr.md): typed contract in `config/env-contract.yaml`, `scripts/env_contract.py` (tests in `tests/test_env_contract.py`), the layered shell-script `.env`, and the secret-source recommendation (OpenBao via the Trust Agent, SOPS and Infisical compared).

## Observability and identity

- [Trust Agent dependency routing](adr/trust_agent_dependency_routing_adr.md): exact TLS aliases on the existing isolated Traefik overlay avoid local Tailscale hairpin failures without widening service networks.
- [Grafana managed ingress alert routing](adr/grafana_managed_ingress_alert_routing_adr.md): alert routing for managed ingress.
- [Volcano Prometheus jobs disabled](adr/prometheus_volcano_targets_disabled_adr.md): retired Kubernetes scrape jobs commented out; deploy needs a `CONFIG_VERSION` bump.
- [Authelia backup direct discovery](adr/authelia_backup_direct_discovery_adr.md): how the backup finds its target.

## Examples

Review-only compose fragments in [examples/](examples/): Pterodactyl DB rotation, panel v1 upgrade overlay, Wings GCS backup volume and native GCS S3 settings. Merge them into the reconciled live stack; never deploy them alone.
