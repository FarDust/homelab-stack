# Redis DB Index Map

Last updated: 2026-03-03

This document lists Redis DB indexes referenced in the repo and the services that use them.
If a service does not specify a DB index, the Redis client typically defaults to DB 0.

## Main Redis (stacks/main/storage.yml)
Service: `main-storage_redis` (Traefik TCP: `redis.${LOCAL_DOMAIN}` on `host-internal`)

| DB index | Service(s) | Source |
|---|---|---|
| 1 | RAGFlow cache/session store | `stacks/retrieval/configs/ragflow/service_conf.yaml.template` (`redis.db`) |
| 3 | CubeJS cache/queue (default via `REDIS_CUBE_DB`) | `stacks/retrieval/analytics.yml` (`CUBEJS_REDIS_URL`) |
| 4 | OpenWebUI main Redis | `.env` (`OPEN_WEB_UI_REDIS_DB`, `OPEN_WEB_UI_REDIS_URL`) |
| 5 | Firecrawl Redis | `.env` (`FIRECRAWL_REDIS_DB`, `FIRECRAWL_REDIS_URL`) + `stacks/retrieval/web.yml` |
| 6 | n8n Bull queue (intended) | `stacks/productivity/automations.yml` (`QUEUE_BULL_REDIS_DB`) |
| 2 | OTel collector queue storage | `stacks/main/logging.yml` + `stacks/main/configs/logging/otel-collector.yml` |
| 7 | n8n chat memory (manual/out-of-repo) | Manual note (not configured in repo) |
| 8 | OpenWebUI websockets | `.env` (`OPEN_WEB_UI_WEBSOCKETS_REDIS_URL`) |
| 9 | Honcho cache/queue | `stacks/llms/agents.yml` (`HONCHO_REDIS_DB`) + `stacks/llms/configs/honcho/init.sh` (`CACHE_URL`) |
| 0 (implicit) | Langfuse (no DB index specified) | `stacks/llms/monitoring.yml` (`REDIS_CONNECTION_STRING`) |
| 0 (implicit) | cAdvisor storage driver (no DB index specified) | `stacks/main/monitoring.yml` (`--storage_driver_host`) |
| 0 (implicit) | RAGFlow (no DB index specified) | `stacks/retrieval/documents.yml` (`REDIS_HOST/PORT/PASSWORD`) |

Notes:
- `QUEUE_BULL_REDIS_HOST` defaults to `redis`; if you intend n8n to use the in-stack `queue` service instead of main Redis, override the host accordingly.
- Repo does **not** set the Redis `databases` count; if you've capped it to 10, ensure all DB IDs remain in the 0–9 range.

## Unassigned (main Redis)
Based on repo references, these DB indexes are currently **unused** on `main-storage_redis`:
none currently tracked

If you want more headroom, we should first verify the Redis `databases` count and then reserve additional indexes explicitly.

## Other Redis Instances (separate services)
These use their **own** Redis service and DB index references, independent of the main Redis above.

| Redis service | DB index(es) | Service(s) | Source |
|---|---|---|---|
| `authelia-redis` (main-traefik stack) | 0 | Authelia sessions | `stacks/main/configs/authelia/configuration.yml` (`database_index: 0`) |
| `redis-searxng` (productivity/tools stack) | 0 | SearxNG | `stacks/productivity/tools.yml` (`redis://...@redis-searxng:6379/0`) |
| `security-redis` (security/network stack) | (not specified) | ntopng | `services/security/network.yml` (`--redis security-redis...`) |
| `cache` (hobby/gaming stack) | (not specified) | Pterodactyl panel | `stacks/hobby/gaming.yml` (`REDIS_HOST=cache`) |
| `queue` (productivity/automations stack) | (not specified) | n8n queue service | `stacks/productivity/automations.yml` (`queue` service) |

If you want this list to include explicit DB indexes for the “not specified” entries, we should set them in the service configs so they’re deterministic.
