# Node-local state and the ephemeral node

Date: 2026-10-13 16:15 UTC

## Context

After gabriel-pc-wsl rejoined at 06:21 UTC on 2026-10-13, ephemeral-rebalance moved every service whose placement allowed it onto that node. Services with node-local Docker volumes then started against whatever volume that node happened to hold. Audit of all 46 services on gabriel-pc-wsl at 15:55 UTC (mounts and constraints from `docker service inspect`, volumes from each node's local Docker root, sizes and file times from the volume directories):

| Service | State | Finding | Action |
| --- | --- | --- | --- |
| `main-logging_loki` | local volume | ran 9 h on an unrelated WSL volume; history on frost-fang unreachable | pinned, see `loki_pinned_placement_adr.md` |
| `hobby-streaming_jackett` | local volume | the Jackett indexers (1337x, limetorrents, thepiratebay, torrentgalaxyclone) exist only on frost-fang; the WSL and fardustdev copies have none, so Sonarr/Radarr searches would have failed | pinned live to storage-manager non-leader (frost-fang); not in the compose repo (no source definition exists) |
| `productivity-automations_n8n` | local volume | community node `@mendable/n8n-nodes-firecrawl` and 100 files exist only on frost-fang; encryption `config` is identical on all three nodes, database is PostgreSQL, so no credential loss | pinned (live and in `automations.yml`) |
| `productivity-finance_firefly-upload-backup` | local volumes | backs up the WSL copy of `firefly_iii_upload` (empty) while `fireflyiii` runs on frost-fang with its own empty copy (0 files on both); nothing lost today, but the backup job cannot see the application's volume if it ever holds files | reported, not changed |
| `mcp-playwright` | local volume | WSL browser cache empty (fardustdev holds 962 MB) | regenerable cache; no action |
| `main-logging_vector` | local volume | checkpoint volume empty on WSL (fardustdev 920 KB) | minor duplicate or missed lines at most; no action |
| streaming (Jellyfin, Sonarr, Radarr, Bazarr, Jellyseerr, qBittorrent), `actual`, `wealthfolio`, ComfyUI cache | local volumes | pinned to the ephemeral node by their own constraints; the only copy of the state is on gabriel-pc | archived to GCS (see below); no move |
| `main-security_crowdsec`, `main-bridges_netdata-child-config`, cadvisor, node-exporter and other global or bind-mounted services | node-specific by design | no action |
| `ollama`, `open-terminal`, `pterodactyl-panel`, notebooks, ComfyUI models | rclone volumes (GCS) | durable | none |
| `langfuse-worker`, `notify`, `firecrawl-worker`, Supabase, Grafana MCP, exporters | no mounts | stateless | none |

## Decision

1. Services with node-local state that must follow their data carry `node.labels.storage.manager == true` and `node.labels.swarm.leader != true` (the Keycloak/Loki pattern; ephemeral-rebalance skips cluster-group constraints). Applied to Loki, Jackett and n8n.
2. Before any move, small state volumes were archived to `gs://<artifacts-bucket>/ephemeral-state-audit/2026-10-13/<node>/` (gz tar, member counts listed, sizes checked against the bucket). Nothing was deleted; the WSL, frost-fang and fardustdev copies of every volume are untouched.
3. Rule for the controller (to be implemented in ephemeral-rebalance): never move a service whose spec mounts a `local`-driver named volume or a bind mount, unless the service is labelled as stateless or pinned by label.

## Alternatives

- Pin every service by hostname: rejected by cluster rules.
- Copy volumes to the destination node before moving: rejected for Jackett and n8n because the freshest copies are the ones on frost-fang and the old copies elsewhere are stale; merging state automatically is riskier than pinning.
- Move the streaming stack off the ephemeral node: it is deliberately there (GPU, local NFS media).

## Consequences

- Jackett and n8n now consume frost-fang capacity and fail to schedule if no non-leader storage-manager node is Ready.
- The streaming and finance state on gabriel-pc has one copy plus the 2026-10-13 archive; a scheduled backup is a follow-up.
- Jackett must gain a definition in `stacks/hobby/streaming.yml` (no source exists); until then the live constraint is the only record.

## Verification

Jackett on frost-fang lists the four indexer files; n8n on frost-fang answers `/healthz` with ok and has `n8n-nodes-firecrawl` installed; archives listed in the bucket with matching sizes (WSL ten, frost-fang two, fardustdev two).
