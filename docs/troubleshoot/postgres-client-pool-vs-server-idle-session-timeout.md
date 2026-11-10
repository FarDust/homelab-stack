# Client connection pools versus the server idle-session timeout

PostgreSQL's `idle_session_timeout` (PostgreSQL 14 and later) terminates a backend that sits idle outside a transaction for longer than the limit. A client pool that keeps connections idle for longer than that limit holds sockets the server has already closed, and hands one to the next caller.

## Mechanism

1. The pool opens a connection and returns it to its idle list after use.
2. The server ends the backend once the idle time passes the limit (`FATAL: terminating connection due to idle-session timeout`).
3. The pool does not learn of it until the socket is used: the next checkout receives a dead connection.
4. The first statement fails (`connection closed`, `server closed the connection unexpectedly`, a Windows `10053` abort, or a pool timeout while the pool replaces it).

The failure is intermittent and follows idleness, not load, so it often looks like a network fault.

## Fix order

1. Make the pool validate or retire connections before the server does: see [pool liveness settings](connection-pool-liveness-settings.md). The client idle lifetime must be shorter than the server limit.
2. Add TCP keepalives only for network-level drops; they do not reset the idle-session clock.
3. Opt a pooled database out of the server limit only when the pool cannot be changed, as decided in [pooled databases opt out of the idle session timeout](../adr/postgres_pooled_idle_session_adr.md).

## Related

- [Pooler orphan connection limits](../adr/pooler_orphan_connection_limits_adr.md)
- [Recognising idle-session timeouts](postgres-idle-session-timeout-triage.md)
- [Warnings printed by every credentialless client](warning-printed-by-every-credentialless-client.md)

Entities: [[PostgreSQL]], [[Supavisor]]
