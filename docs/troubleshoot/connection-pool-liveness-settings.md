# Connection pool liveness settings

Keep every client pool's idle lifetime below the server's idle limit and validate connections that were idle. Examples by library:

| Client | Validate on checkout | Retire idle connections |
| --- | --- | --- |
| psycopg_pool | `check=ConnectionPool.check_connection` | `max_idle` below the server limit (the default is 10 minutes) |
| SQLAlchemy | `pool_pre_ping=True` | `pool_recycle` below the server limit |
| asyncpg | none built in | `max_inactive_connection_lifetime` below the server limit |
| Prisma | none built in | lower the pool idle lifetime through the connection-string parameters |

Pick the retire value with margin: with a 60 second server limit, use 30 seconds or less so a connection is never handed out in the last seconds of its life.

A `min_size` of zero is fine (a burst after an idle period just opens new connections); the failure is a pool that keeps connections and never checks them.

Verify with a test that opens a connection, lets the server end it while idle, then checks that the pool replaces it instead of raising.

## Related

- [Client pools versus the server idle-session timeout](postgres-client-pool-vs-server-idle-session-timeout.md)
- [Recognising idle-session timeouts](postgres-idle-session-timeout-triage.md)

Entities: [[PostgreSQL]]
