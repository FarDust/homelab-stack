# Redis DB Index Map

Last audited: 2026-10-04 16:46 UTC

Migration update: 2026-10-10 04:24 UTC. The cluster RQ worker uses repaired
`main-storage_redis` DB10 with queue `cluster.example.v1`. Its original DB0 records
and dedicated `main-messaging_rq-redis` DB10 historical results/control keys remain
retained on volume `main-messaging_rq_redis_data`. Gabriel waived live rollback and
retention duration; the dedicated service, route, config and secret are retired.
Restore the prior source definition only for explicitly approved recovery or
evidence review, and preserve the existing volume.

## Instance identity comes before database number

This registry concerns the standalone `main-storage_redis` service from
`stacks/main/storage.yml`. Logical DB numbers belong to an instance: DB 0 on
Authelia's Redis is not DB 0 on the main Redis. Resolve the service/host before
interpreting a DB index. The main instance is reached through the existing
Traefik `host-internal` TLS route.

## Main Redis assignments

| DB | Owner / purpose | Evidence and status |
|---|---|---|
| 0 | Legacy/default consumers: Langfuse, cAdvisor and a RAGFlow configuration; LiteLLM declares a Redis host without a DB in its service environment | Historical map plus current Swarm/config audit. This is shared/default space, not a free first-party allocation. Agent-work currently also has its temporary prefixed key here. |
| 1 | RAGFlow cache/session configuration | Historical assignment in `stacks/retrieval/configs/ragflow/service_conf.yaml.template`; retain reservation even when empty. |
| 2 | OpenTelemetry collector queue storage | `OTEL_COLLECTOR_REDIS_DB=2` in current service specification and `stacks/main/logging.yml`; connected client observed. |
| 3 | CubeJS cache/queue | Historical `REDIS_CUBE_DB` / `CUBEJS_REDIS_URL` assignment in `stacks/retrieval/analytics.yml`; not proved active by this audit. |
| 4 | Open WebUI application state | Current `REDIS_URL` explicitly selects 4. |
| 5 | Firecrawl application/rate-limit queues | Current API and worker `REDIS_URL` / `REDIS_RATE_LIMIT_URL` select 5. |
| 6 | n8n Bull queue | Current `QUEUE_BULL_REDIS_DB=6`; source now uses `N8N_QUEUE_BULL_REDIS_DB` with default 6. Declaration does not alone prove queue mode is active. |
| 7 | n8n chat memory | Existing manual/out-of-repository reservation; retain until its owner releases it. |
| 8 | Open WebUI WebSockets | Current `WEBSOCKET_REDIS_URL` explicitly selects 8. |
| 9 | Honcho; conflicting legacy Dokploy declaration | Both current Swarm specifications declare 9. Both were at 0/0 replicas during audit. Resolve ownership before re-enabling either; do not repurpose based on empty keyspace. |
| 10 | Active first-party agent-work and RQ control plane | Repaired shared persistence; cluster worker consumes only `cluster.example.v1`, while the Windows worker queue remains `agent-work-ncc-altair.windows.gabriel-pc`. |
| 11-15 | Unallocated in the reviewed registry | Enabled and no keys/connected clients observed at audit time. Allocate individually after checking current owners and configurations; emptiness alone is not ownership evidence. |

## Semantic rule for implementations we own

There is no built-in semantic meaning to a Redis DB number. This cluster's
convention is an explicit consumer/purpose allocation, not one undifferentiated
database for all custom code. DB 10 is assigned to the first-party agent-work
control plane: queue jobs, coordination and their supporting state. Future
unrelated first-party applications receive their own registry entry and DB when
appropriate; sharing one requires an explicit compatible lifecycle/ownership rule.

Use maintained RQ for Python job-queue behavior rather than a parallel homemade
queue. Keep application-specific goals, attempts and acceptance evidence distinct
from RQ job status. RQ's own keys and registries are an additional reason not to
mix this service into legacy DB 0. Within DB 10 retain a stable application prefix
and distinct queue names; do not rewrite library internals just for naming.

Logical DBs separate key names and a DB-scoped flush, but are not security,
resource, eviction-policy or persistence isolation. Redis ACL/key restrictions,
credentials, memory policy and backups must be evaluated separately. Pub/Sub
channels also require namespacing; SELECT does not isolate them.

## Observed runtime, not a timeless guarantee

Read-only audit used CONFIG GET, INFO keyspace, CLIENT LIST database counts,
current Swarm service environments, canonical `.env`, and Redis-bearing stack
files. Credentials, connection URLs and key values were omitted from the report.

- Configured databases: **16**, indexes 0 through 15. No expansion is required
  to reserve DB 10. The earlier suggestion that only 0-9 might exist is superseded.
- Eviction policy: **noeviction**. Memory exhaustion can reject writes; this is
  not a durability or availability guarantee.
- Nonempty DBs at the sample: 0, 2, 4, 5 and 8. Connected clients selected 0, 2
  and 5; the auditor itself contributes a connection to DB 0.
- No DB 10-15 consumer was found in the audited Swarm environment or stack
  references. Offline/manual applications outside this scope are not fully
  attributable; the documented DB 7 reservation illustrates why emptiness is
  insufficient evidence for reassignment.
- AOF is enabled and the repaired service mounts the named volume at the active
  `/bitnami/redis/data` directory. The data-preserving repair and source/runtime
  mount proof are recorded in
  `reports/main-storage-redis-persistence-repair-20261004-2317.md`.

## Migration status and procedure

Agent-work's original four-record revision-24 snapshot moved from DB0 to main
Redis DB10, retaining source. After ownership reconciliation, five-record revision39
was copied exactly to isolated main-messaging Redis DB10, preserving attempts and
checkpoints (SHA256 `6056f4d6d4225f63b4172beaa24a25dd28bd677bad18c527c19e548318ed3554`).
The Windows RQ worker executed a real OpenCode task, retained finished jobs, and
left application acceptance to an explicit parent review. After shared Redis
persistence was repaired, the cluster worker moved to `main-storage_redis` DB10 and
completed JSON `cluster.example.v1` retained-result canaries before and after the
dedicated Redis retirement. The cluster worker is not subscribed to the Windows
queue. Old source records, dedicated Redis historical results/control keys, and
checkpoints remain on the retained volume. See `docs/messaging.md`,
`reports/main-messaging-rq-worker-shared-redis-db10-20261005.md`, and agents-utils
`docs/rq-migration.md`. Never FLUSHDB/FLUSHALL; endpoint rollback after new writes
requires state reconciliation.

The current queue harness's recovery guard rejects missing or rolled-back state.
Changing a URL alone is not a migration. Its configured database number and the
documented reservation must be reported separately until the transition finishes.

## Separate Redis instances

| Service / instance | DB | Purpose / source |
|---|---|---|
| `main-messaging_rq-redis` | 10 | Retired dedicated instance. Historical RQ results/control keys remain only on preserved Docker volume `main-messaging_rq_redis_data`; the live service, route, config and secret are removed and the cluster worker does not consume it. |
| `main-traefik_authelia-redis` | 0 | Authelia sessions; `stacks/main/configs/authelia/configuration.yml`. |
| `redis-searxng` | 0 | Historical SearXNG configuration in `stacks/productivity/tools.yml`; separate instance reference, not a main-Redis reservation. |
| `security-network_security-redis` | not explicitly assigned in the old map | ntopng; inspect its consumer before changing. |
| `hobby-gaming_cache` | default unless its client overrides it | Pterodactyl; current panel declares host `cache`. |
| n8n `queue` service | default unless its client overrides it | Historical separate-instance configuration. Current n8n specification inspected here points to host `redis`, DB 6. |

The vault reference mirrors this canonical document. The general Redis system
note describes the Redis ecosystem and is not authoritative for per-instance DB
allocation. Re-audit deployment values before future reassignment.
