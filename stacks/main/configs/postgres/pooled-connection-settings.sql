-- Connection hygiene for roles reached through Supavisor pools.
-- Orphaned backends left by dead pooler tasks must die on their own and must not
-- starve a role's CONNECTION LIMIT (error 53300); as decided in
-- docs/adr/pooler_orphan_connection_limits_adr.md.
--
-- Idempotent. Apply as a superuser against the main-storage_postgres server
-- (no restart needed; the keepalive settings are reloadable):
--   docker exec -u postgres <container> psql -d postgres -v ON_ERROR_STOP=1 -f pooled-connection-settings.sql
-- Keepalives apply to sessions opened after the reload. Idle probing starts at 60 s
-- and a silent peer is dropped after 60 + 6 * 10 = 120 s.

ALTER SYSTEM SET tcp_keepalives_idle = 60;
ALTER SYSTEM SET tcp_keepalives_interval = 10;
ALTER SYSTEM SET tcp_keepalives_count = 6;
SELECT pg_reload_conf();

-- rolconnlimit leaves room for the live pools plus one orphaned generation (about
-- 120 s after a pooler task dies, a restart loop can overlap two generations).
-- loglynx: tenant apps-pgpool-tx, pool_size 8, session and transaction pools
--          8 * (2 pools + 1 orphaned generation) = 24
-- vizlord: tenant apps-pgpool pool_size 18 + tenant grafana pool_size 5 = 23
--          23 * (live + 1 orphaned generation) = 46
ALTER ROLE loglynx CONNECTION LIMIT 24;
ALTER ROLE vizlord CONNECTION LIMIT 46;
