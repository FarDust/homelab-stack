# Cluster documentation

## Speech and model serving

- [LiteLLM local text-only fallback](adr/litellm_local_text_fallback_adr.md): local Gemma 3 4B as the last hop of text-only aliases, the no-tools rule, node-local weights (no GCS egress), placement, rollback (tests in `tests/test_litellm_local_text_fallback.py`).
- [vLLM Gemma read routes](adr/vllm_gemma4_read_routes_adr.md): `GET`/`HEAD` reach the scale-to-zero engine without waking it; every other method, inference included, can start a Sablier session (tests in `tests/test_vllm_gemma4_read_routes.py`).
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
- [Staggered start of GPU and AI services](adr/gpu_node_staggered_start_adr.md): uptime-slot startup gate and ordered restart delays so the ephemeral node's services come up one at a time after a VM start (tests in `tests/test_gpu_node_staggered_start.py`).
- [Redis database IDs](redis-db-ids.md): per-service Redis database allocation.
- [Netdata parent image and memory budget](adr/netdata_parent_memory_budget_adr.md): parent metadata growth from container churn fixed by v2.12.2+, 6G limit with 4G reservation, implicit swap allowance, rollback (tests in `tests/test_netdata_parent_budget.py`).

## Configuration and secrets

- [Private deployment directory](homelab-private.md): `HOMELAB_PRIVATE_DIR`, the files each stack expects there, and the templates in `examples/homelab-private/`.
- [PR-Agent CI review](adr/pr_agent_ci_adr.md): A2A review server behind LiteLLM, the `scripts/pr-agent-review.py` client, tailnet-only reachability and key renewal.
- [Environment-variable contract](adr/env_contract_adr.md): typed contract in `config/env-contract.yaml`, `scripts/env_contract.py` (tests in `tests/test_env_contract.py`), the layered shell-script `.env`, and the secret-source recommendation (OpenBao via the Trust Agent, SOPS and Infisical compared).

## Observability and identity

- [Trust Agent dependency routing](adr/trust_agent_dependency_routing_adr.md): exact TLS aliases on the existing isolated Traefik overlay avoid local Tailscale hairpin failures without widening service networks.
- [Traefik immutable image pin](adr/traefik_image_pin_adr.md): configuration-only deployments retain the reviewed proxy image digest.
- [Grafana managed ingress alert routing](adr/grafana_managed_ingress_alert_routing_adr.md): alert routing for managed ingress.
- [Volcano Prometheus jobs disabled](adr/prometheus_volcano_targets_disabled_adr.md): retired Kubernetes scrape jobs commented out; deploy needs a `CONFIG_VERSION` bump.
- [Authelia backup direct discovery](adr/authelia_backup_direct_discovery_adr.md): how the backup finds its target.

## Troubleshooting notes

Small, generic notes in [troubleshoot/](troubleshoot/); the vault sync turns their links into wikilinks.

- Database pooling: [pool versus server idle-session timeout](troubleshoot/postgres-client-pool-vs-server-idle-session-timeout.md), [triage](troubleshoot/postgres-idle-session-timeout-triage.md), [pool liveness settings](troubleshoot/connection-pool-liveness-settings.md), [warning printed by every credentialless client](troubleshoot/warning-printed-by-every-credentialless-client.md).
- Secrets in output: [`docker stack config` prints resolved secrets](troubleshoot/docker-stack-config-prints-resolved-secrets.md), [scrubbing a leaked secret](troubleshoot/scrubbing-a-leaked-secret-from-transcripts.md).
- Docker networking: [published ports unreachable from containers (Docker 29.8)](troubleshoot/docker-29-8-published-ports-unreachable-from-containers.md), [gwbridge ingress DNAT remediation](troubleshoot/gwbridge-ingress-dnat-remediation.md), [gwbridge return routing](troubleshoot/docker-gwbridge-return-routing.md), [reversible live network changes](troubleshoot/dead-man-switch-for-live-network-changes.md).
- LiteLLM local fallback: [design](troubleshoot/litellm-local-text-only-fallback-design.md), [tool requests excluded](troubleshoot/litellm-tool-requests-excluded-from-local-fallback.md), [testing egress cost](troubleshoot/litellm-fallback-testing-egress-cost.md), [config version rollback](troubleshoot/litellm-config-version-rollback.md), [cold start versus caller timeout](troubleshoot/local-model-cold-start-versus-caller-timeout.md).
- Node loss and the WSL node: [node loss with a retained boot volume](troubleshoot/node-loss-with-retained-boot-volume.md), [capacity retry loops](troubleshoot/capacity-retry-loops-need-caps-and-fail-closed-state.md), [data disk after a WSL VM rebuild](troubleshoot/wsl-ephemeral-node-data-disk-after-vm-rebuild.md), [exec failure is not guest down](troubleshoot/wsl-exec-failure-is-not-guest-down.md), [WSL and Tailscale MTU black hole](troubleshoot/wsl-tailscale-mtu-black-hole.md).

## Examples

Review-only compose fragments in [examples/](examples/): Pterodactyl DB rotation, panel v1 upgrade overlay, Wings GCS backup volume and native GCS S3 settings. Merge them into the reconciled live stack; never deploy them alone.
