# Recognising idle-session timeouts

Use this when an application reports a database error right after a quiet period and the database itself is healthy.

## Signals

- Client errors that appear after idleness: pool timeout, `connection abort 10053`, `server closed the connection unexpectedly`, `Server has closed the connection`.
- Server log lines: `terminating connection due to idle-session timeout`, one per killed backend.
- A pooler reporting a backend termination at the same time.
- Retrying the same call a second later succeeds.

## Confirm in two reads

```sql
show idle_session_timeout;

select d.datname, r.rolname, array_to_string(s.setconfig, ',')
  from pg_db_role_setting s
  left join pg_database d on d.oid = s.setdatabase
  left join pg_roles r on r.oid = s.setrole;
```

Then count server log lines containing `idle-session timeout` per role in the failure window; a count that tracks the client error count proves the cause.

## Rule out first

Check that the service is up, that the listener accepts connections (`pg_isready`), and that the role is far from its connection limit. A healthy server with terminated idle backends points at the pool, not at the network.

## Related

- [Client pools versus the server idle-session timeout](postgres-client-pool-vs-server-idle-session-timeout.md)
- [Pool liveness settings](connection-pool-liveness-settings.md)

Entities: [[PostgreSQL]]
