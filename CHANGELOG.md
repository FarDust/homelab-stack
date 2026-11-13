# Changelog

## 0.1.8

- Fix `main/traefik`: the `HOMELAB_PRIVATE_DIR` required-variable messages contained hyphens, which `docker stack deploy` reads as the default operator, so the Prometheus ingress probe targets and five Grafana dashboards resolved to a wrong path and the services could not be redeployed. Messages are hyphen-free and guarded by a test. See `docs/adr/swarm_interpolation_required_message_adr.md`.

## 0.1.7

- Docs: the HDD-backed node record now covers memory. Job scratch moved to tmpfs became swap-out; adds the admission signal, the per-job footprint, the node budget and the runtime zswap change. No stack configuration changes.

## 0.1.6

- ClickHouse: pin the exact running release by digest and remove the self-telemetry tables (`trace_log`, `text_log`, `metric_log`, `asynchronous_metric_log`, `part_log` and related) that wrote to the data disk around the clock; `query_log` and `crash_log` stay. Existing tables are kept.
- Prometheus: `HostIoPressureSustained` and `HostDiskSaturated` alerts with rule tests.
- Docs: troubleshooting note for throwaway test databases. See `docs/adr/hdd_node_io_budget_adr.md`.

## 0.1.5

- Static journey nginx: compress text assets with gzip and serve a static `/reset` recovery page with `Cache-Control: no-store`. The versioned config name changes with `JOURNEY_VERSION`, so the next rollout of the stack picks it up.

## 0.1.4

- Stagger the start of the GPU and AI services on the ephemeral GPU node after a VM start: an uptime-slot startup gate in the entrypoint of whisper, ollama, jellyfin, jellyseerr, sonarr, radarr, bazarr, qbittorrent, jupyter-tensorflow and comfy-gpu, ordered restart delays, memory reservations and a longer whisper start period. `vllm-gemma4` stays at zero replicas. See `docs/adr/gpu_node_staggered_start_adr.md`.

## 0.1.3

- Pin Traefik to the previously deployed immutable digest so a routing-only service update cannot silently upgrade the proxy through the floating `latest` tag.

## 0.1.2

- Resolve the exact OpenBao and Keycloak TLS hostnames to Traefik's existing `trust-internal` endpoint for Trust Agent consumers. This preserves TLS/SNI and network segmentation while avoiding an unreachable container-to-local-Tailscale hairpin.

## 0.1.1

- Refresh vulnerable Python dependency locks within the existing declared constraints, including AnyIO 4.14.2, LiteLLM 1.88.6, aiohttp 3.14.3, urllib3 2.8.0, Mako 1.4.2, multidict 6.9.1, and patched HTTP, parsing, and serialization dependencies.
- Preserve the existing cryptography 46, virtualenv 20, langsmith 0.6, and langgraph-sdk 0.3 compatibility lines. Advisories requiring incompatible upgrades remain open for a separately validated migration.
- Keep the editable cluster-utils source declaration unchanged. No stack configuration, deployment, service state, or credentials are changed.
