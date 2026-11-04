# Pooled databases opt out of the server-wide idle session timeout

Status: accepted, 2026-10-12.
Applies to: `main-storage_postgres`, database `langfuse`.
Implementation: `stacks/main/configs/postgres/database-session-settings.sql`.
Evidence: the operator report is kept in the private deployment records.

## Context

`main-storage_postgres` runs with `idle_session_timeout = 60s` set server-wide
through `ALTER SYSTEM` (`postgresql.auto.conf`). It was already live when TRA-223
inspected it on 2026-03-13 and no record explains why it was introduced. TRA-223
identified the same timeout as the cause of Grafana's database churn at the time.

Langfuse web and worker reach the database only through the apps Supavisor
pooler on its session port. In session mode each Prisma pool connection owns one
PostgreSQL backend. Prisma keeps idle pool connections for about 300 seconds
before recycling them, so the server killed many of them while the pool still
held them. Supavisor then reports `DbHandler ... {:shutdown, :db_termination}`
and, when the pool reused the connection first, Prisma raised
`Server has closed the connection`. Between 06:00 and 18:30 UTC on 2026-10-12
PostgreSQL logged 72 idle-session terminations for the Langfuse role; two of
them coincided with Langfuse worker failures. The PostgreSQL documentation
cautions against enforcing this timeout on connections made through pooling
middleware.

## Decision

Keep the server-wide value and set `idle_session_timeout = 0` for the `langfuse`
database only. The client pool owns idle lifetime for those backends. Extend the
same override to other pooled databases only with their own evidence.

## Alternatives considered

- Set the server-wide timeout to 0: also removes the Grafana, LiteLLM and Gatus
  terminations, but changes behavior for every database and for unpooled
  clients whose original rationale is unknown. Deferred until that rationale is
  reviewed.
- Raise the server-wide timeout above every pool's idle lifetime: still breaks
  pools with longer lifetimes (Grafana keeps connections for hours).
- Per-role override: misses other roles that reach `langfuse` through the same
  pooler tenant.
- Switch Langfuse to the transaction port: changes Prisma prepared-statement
  behavior and the tenant contract; out of proportion for this failure.

## Consequences

- Idle `langfuse` backends now live until Prisma recycles them (about 300 s).
  Backend count stays bounded by Prisma `connection_limit` per runtime and the
  Supavisor tenant user pool sizes (10 in total). The server has 90
  non-reserved slots; about 40 were in use on 2026-10-12.
- A leaked or crashed `langfuse` client keeps its backend until TCP failure
  detection closes it, instead of 60 seconds.
- The setting lives in the PostgreSQL catalog (`pg_db_role_setting`). Re-apply
  the SQL file after restoring or recreating the `langfuse` database.

## Verification

- `select array_to_string(setconfig, ',') from pg_db_role_setting s join
  pg_database d on d.oid = s.setdatabase where d.datname = 'langfuse';` returns
  `idle_session_timeout=0`.
- A new session in `langfuse` returns `0` for `show idle_session_timeout;`.
- After existing backends rotate, PostgreSQL logs no further
  `terminating connection due to idle-session timeout` for `langfuse` sessions.
  Observed on 2026-10-12: none between 19:07:30 and 19:21 UTC, after 2 in the
  preceding 16 minutes.
