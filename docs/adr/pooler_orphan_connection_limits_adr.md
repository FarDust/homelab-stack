# Pooler orphan connections and role connection limits

Status: accepted, 2026-10-13.
Applies to: `main-storage_postgres` roles `loglynx` and `vizlord`; `main-storage_supavisor-apps`.
Implementation: `stacks/main/configs/postgres/pooled-connection-settings.sql`,
`stacks/main/storage.yml` (service `supavisor-apps`),
`stacks/main/configs/postgres/postgres_exporter_queries.yaml` (`pg_role_activity`).
Evidence: the supporting report is kept in the private deployment records.
Related: `docs/adr/postgres_pooled_idle_session_adr.md`,
The related pool-reset report is kept in the private deployment records.

## Context

On 2026-10-12 the apps pooler returned SQLSTATE 53300 (too many connections for
role "loglynx"). The role has `rolconnlimit = 8` and the Supavisor tenant
`apps-pgpool-tx` (user `loglynx`, database `langfuse`) has `pool_size = 8`, so
the limit equalled one full pool and left no room for anything else. Supavisor
tasks were being replaced every few minutes that night (frost-fang I/O stalls,
manager session loss). Each dead task left its upstream backends open: seven
idle `loglynx` backends from the IPVS SNAT address 198.51.100.10 had to be
terminated by hand before the replacement pool could connect.

Why orphans survive: PostgreSQL had `tcp_keepalives_idle/interval/count = 0`
(kernel defaults, first probe after 7200 s) and the Supavisor image never sets
SO_KEEPALIVE on its Erlang sockets (no `keepalive` atom in any
`supavisor-2.7.4` beam). A peer that vanishes without FIN or RST (task killed
while the overlay is stalled) is therefore noticed by nobody for two hours.

The same shape exists for `vizlord` (Grafana): tenant `apps-pgpool` pool 18,
tenant `grafana` pool 5, role limit 18. The tenant pool sizes live in the
`supavisor_apps` metadata database (`_supavisor.users`), not in repository seeds
(`apps_pooler.exs` seeds only the `grafana` and `langfuse` tenants).

## Decision

1. Orphans die on their own, on both ends:
   - PostgreSQL: `tcp_keepalives_idle = 60`, `tcp_keepalives_interval = 10`,
     `tcp_keepalives_count = 6` through `ALTER SYSTEM` (reloadable, no restart);
     a silent peer is dropped after about 120 s. Applies to new sessions.
   - Supavisor: `ERL_AFLAGS` gains `-kernel inet_default_connect_options
     [{keepalive,true}] inet_default_listen_options [{keepalive,true}]`, and the
     service sets `sysctls` `net.ipv4.tcp_keepalive_time=60`, `..._intvl=10`,
     `..._probes=6` (namespaced, per container). Same 120 s bound for a dead
     PostgreSQL or a dead client.
2. Role limits cover the pools plus one orphaned generation:
   `loglynx` 8 to 24 (8 x session pool, transaction pool, orphaned generation),
   `vizlord` 18 to 46 ((18 + 5) x live plus orphaned generation). The server has
   100 slots with 10 reserved and about 45 in use, so the fence still protects
   other tenants. Rule for new pooled roles: `rolconnlimit >= pool_size x
   (pool modes + 1)`, never equal to a pool size.
3. Detect the condition before 53300: the exporter query `pg_role_activity`
   exports `pg_role_activity_connections` per role; the alert compares it with
   the existing `pg_roles_connection_limit` (ratio above 0.75 for 5 minutes,
   Grafana-managed per `docs/adr/grafana_managed_ingress_alert_routing_adr.md`).

## Alternatives considered

- Lower the tenant pool to fit the limit: Langfuse then queues under load, and
  the limit would still equal the pool, so one orphan generation blocks it.
- Transaction-pool mode only: the Langfuse route uses the session port; changing
  mode changes the Prisma prepared-statement contract (see the idle-session ADR).
- Remove the limits (`-1`): drops the fence that protects the 90 usable slots.
- Keepalives only in PostgreSQL: cleans orphans but leaves Supavisor blind to a
  dead database; the request asked for both ends.
- Set the PostgreSQL values through `EXTRA_CONF` in `storage.yml`: it recreates
  the database container, which needs a data-safety window; `postgresql.auto.conf`
  on the data volume is the same persistence the idle-session override uses.
- Raw TCP_KEEPIDLE socket options in `ERL_AFLAGS`: OTP-version specific; sysctls
  are simpler and visible with `docker service inspect`.

## Consequences

- Existing PostgreSQL sessions keep the old timers until they recycle; only new
  sessions get the 60 s probes.
- Re-apply `pooled-connection-settings.sql` after restoring or recreating the
  cluster (role limits and `postgresql.auto.conf` live in the data volume).
- The `supavisor-apps` `DATABASE_URL` host is `tasks.postgres` (live workaround
  from an earlier monitoring session recorded in the private deployment records); the source now matches
  the live value so a deploy does not revert it.
- `supavisor-k3s` (`bridges.yml`) is unchanged; its role `assimilation` has limit
  40 against pool 20 and no incident. Extend the same keepalive settings there
  with its own evidence.
- Live tenant rows are not reproducible from the repository; importing them into
  the seed script is a follow-up.

## Verification

- `select name, setting, applied from pg_file_settings where name like
  'tcp_keepalives%'` returns 60, 10, 6 applied; `select rolname, rolconnlimit
  from pg_roles where rolname in ('loglynx','vizlord')` returns 24 and 46.
  (`pg_settings` shows 0 over a Unix socket; check `/proc/net/tcp` timers on
  port 5432 sockets: new sessions carry a keepalive timer of 60 s or less.)
- Supavisor task: `docker service inspect` shows the three sysctls and
  `ERL_AFLAGS`; inside the container the sysctls read 60, 10, 6 and established
  sockets carry keepalive timers.
- `pg_role_activity_connections / on(rolname) pg_roles_connection_limit` returns
  a ratio per limited role in Prometheus.
- Consumers (Langfuse web and worker, PostgreSQL log) show no 53300 for 15
  minutes after the deploy.
