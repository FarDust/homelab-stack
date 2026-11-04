# Reusable messaging and RQ operations

Deployed and verified: 2026-10-04 18:30 UTC. Owner: cluster operations.
Canonical source: `stacks/main/messaging.yml`; runtime package/configuration:
`stacks/main/configs/messaging/`. Evidence: `reports/messaging-20261004/`.

## Components and deliberate boundaries

| Service | Role | Persistent storage |
|---|---|---|
| `main-messaging_rabbitmq` | RabbitMQ 4.2.5, AMQP 0-9-1 broker with quorum queues/DLQ | `main-messaging_rabbitmq_data` at `/var/lib/rabbitmq` |
| `main-messaging_rq-redis` | Retired 2026-10-10 after owner waiver of live rollback and retention duration | Live service/config/secret removed; recovery copy remains in Docker volume `main-messaging_rq_redis_data` |
| `main-messaging_rq-worker` | RQ 2.12.0, JSON serializer, scheduler, `cluster.example.v1` queue | Results/registries in shared `main-storage_redis` DB10 |

RabbitMQ and RQ are independent. RQ consumes Redis jobs, not AMQP messages. No
bridge, HTTP dispatcher endpoint, or Windows filesystem access is implied.
The Windows agent-work consumer uses its own queue
`agent-work-ncc-altair.windows.gabriel-pc` and its existing local OpenCode API.

RabbitMQ replaces the initial NATS trial because the user prioritizes native DLQ,
low-volume homelab operation and restart-resistant disk persistence. Kafka's
partitioned streaming/replay model and greater operational burden are unnecessary.
NATS was removed; its unused volume/secrets were retained, not mass-pruned.

## Durability and resource limits

One stable RabbitMQ node (`rabbit@cluster-messaging-rabbitmq`) and single-member
quorum queues provide disk-backed restart survival, **not host-loss HA**. A stable
container hostname is broker data identity, not Swarm hostname placement pinning.
All placement uses existing storage/load/non-ephemeral labels, currently fardustdev.
Local volumes do not migrate with a task onto another host. Before changing these
labels or placement, transfer/restore the volume and verify message ownership.

RabbitMQ: 512MiB container limit, 256MiB memory alarm, 1GB free-disk floor,
two Erlang schedulers. Observed idle memory approximately 93MiB. RQ worker observed
approximately 20MiB, limited to 512MiB. The retired dedicated Redis service had
used a 384MiB container limit, 256MiB maxmemory, noeviction and everysec AOF;
those settings are historical recovery context only. The active worker uses
repaired `main-storage_redis` DB10;
its mounted persistence and consumer recovery are documented in
`reports/main-storage-redis-persistence-repair-20261004-2317.md`. Neither instance
is described as host-loss HA or off-host disaster recovery by this document.

## Credentials, networking and project onboarding

Native endpoint on the existing VPN-only Traefik TLS entrypoint (port 5578):
`rabbitmq.${LOCAL_DOMAIN}:5578`. AMQP clients use TLS and SNI for the RabbitMQ
hostname. The retired `rq-redis.${LOCAL_DOMAIN}:5578` route was removed; RQ
clients use the approved shared Redis allocation or another explicitly assigned
backend. Inside the approved overlay, use full service names and native ports. No
new host-published ports or public UI.

Manager credential files remain mode 0600. RabbitMQ uses
`secrets/messaging/rabbitmq_password`. The RQ worker uses the existing shared
`secrets/redis/redis_password`, mounted as `redis_password`. The retired dedicated
Redis secret is no longer part of the live stack; recreate it only as part of an
explicit recovery from the preserved source definition.
RabbitMQ bootstrap user and vhost are `platform`. This is an operator account,
not the credential for every project. Retrieve through approved in-memory secret
providers. Keep values out of argv, URLs in logs, source, reports and examples.

For each application:
1. Assign an owner and dedicated RabbitMQ vhost/user. Grant only its required
   exchange/queue configure/write/read permissions. Keep bootstrap credentials private.
2. Name resources `<project>.<purpose>.v1`, e.g. `billing.events.v1`,
   `billing.work.v1`, `billing.dead.v1`. Document producers, consumers and retention.
3. Create durable work and DLQ quorum queues. Bind the DLQ to a durable dead-letter
   exchange. Configure a policy for `dead-letter-exchange`, routing key,
   `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, a finite
   `delivery-limit`, and `max-length` or `max-length-bytes` appropriate to disk budget.
4. Publish persistent messages (`delivery_mode=2`) with publisher confirms and
   mandatory routing. An unroutable or rejected publish is an explicit failure.
5. Ack only after the application side effect is committed. Use idempotent handlers:
   network loss can redeliver. Nack with `requeue=False` routes a poison message to
   DLQ; bounded retries are separate from successful processing. Inspect and repair
   the cause before controlled replay. Do not implement an endless requeue loop.

The executable `configs/messaging/verify.py` is a concrete Pika producer/consumer
example: confirmed publish, explicit ack, rejection to DLQ, persistent messages,
RQ enqueue, delayed retry and retained-result checks. It creates only run-namespaced
resources and reads its broker credential from stdin. It is a verification tool,
not a general application service or credential-distribution interface.

For RQ projects, assign an explicit Redis instance/DB and unique queue name.
Shared `main-storage_redis` DB10 is the active first-party agent-work/RQ allocation.
The dedicated `main-messaging_rq-redis` service, route, config and secret are
retired; its volume `main-messaging_rq_redis_data` is retained only as historical
migration/recovery data and is not an active routing target for new work. Future
unrelated applications require allocation review.
Logical DBs and queue names are not access-control, memory or persistence isolation.
Use separate backends/credentials for untrusted applications; shared trusted
workers must not accept arbitrary import paths from untrusted producers.

## RQ job packaging, semantics and scaling

`pyproject.toml` + `uv.lock` pin the worker's dependency graph. Official uv/Python
image installs with `uv sync --frozen --no-dev`; no custom image was required.
Cold starts currently require package-index availability. For project workers,
package importable versioned functions and lock dependencies on both producer and
worker. Mount small modules as versioned Swarm configs, as with `jobs_v1.py`;
larger immutable application images require the usual explicit image approval.
Keep old function versions available until their queued jobs have drained.

Example producer in the same approved runtime:

```python
from redis import Redis
from rq import Queue, Retry
from rq.serializers import JSONSerializer
from rq_settings import REDIS_URL  # reads the mounted secret; never print it

with Redis.from_url(REDIS_URL) as connection:
    queue = Queue("cluster.example.v1", connection=connection, serializer=JSONSerializer)
    job = queue.enqueue("jobs_v1.echo", "hello", job_timeout=120,
                        result_ttl=86400, failure_ttl=604800,
                        retry=Retry(max=2, interval=[10, 30]))
    print(job.id)  # accepted by queue, not completed or accepted by application
```

RQ owns worker execution, scheduling, retries and failed/finished registries.
Workers use `--with-scheduler` for delayed retries; JSON is set on both ends.
Default RQ result retention is not a business audit log: set result/failure TTL
explicitly, preserve application acceptance evidence separately. The cluster worker
has 150s stop grace; demo jobs use 120s timeout. Coordinate these for longer jobs.
Worker TTL is 90s and health allows 120s heartbeat age, avoiding idle false failures.
Scale stateless worker replicas in canonical compose and deploy the single service.
Do not scale the single Redis or RabbitMQ service to multiple independent replicas.

## Deploy, health, recovery and rollback

```bash
# REPO is the root of the canonical compose checkout
cd "$REPO"
set -a; . ./.env; set +a
docker compose -f stacks/main/messaging.yml config --quiet
uv run cluster-utils validate deployment main-messaging --service-name rq-worker --compose-file stacks/main/messaging.yml
uv run cluster-utils deploy service rq-worker --compose-file stacks/main/messaging.yml --stack-name main-messaging --timeout 300
```

Use `--bump-config` for changed config/secret content. The new stack was initially
created through the documented `deploy stack` path; it contained only owned
services. Later changes use `deploy service`; no `--force-unsafe` was used.
Cluster-utils can report convergence before UpdateStatus is complete, and its
optional force step hit an update-version race. Keep that failure visible; inspect
the actual new task identity, completed update and health before semantic checks.

Inspect `docker service ps`, container health, RabbitMQ `rabbitmq-diagnostics`,
queue depth/unacked/DLQ counts with `rabbitmqctl list_queues -p <vhost>`, and RQ
worker heartbeats/failed registry. No new Prometheus dashboard is claimed.
Avoid dumping job payloads, environment or credential-bearing logs.

Retired dedicated Redis recovery is source restoration, not a standing live
rollback target. To inspect or recover it, restore the prior `rq-redis` service,
`rq_redis_data` volume declaration, `rq_redis_password` secret declaration,
`redis_start` config declaration and `configs/messaging/redis-start.sh` from git
history or this report, recreate only the dedicated secret from the approved
secret provider, and deploy the restored service against the existing Docker
volume `main-messaging_rq_redis_data`. Do not delete, rename, truncate, migrate or
mount that volume read-write except during an explicitly approved recovery.
After consumers write to the new Redis, application rollback requires reconciling
and reverse-copying the latest owned state, not merely switching to an older URL.
See agents-utils `docs/rq-migration.md` for Windows migration receipts and rollback.
