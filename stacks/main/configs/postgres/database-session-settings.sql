-- Session settings for databases reached only through Supavisor session pools.
-- The server-wide idle_session_timeout (60s in postgresql.auto.conf) terminates
-- backends that client pools still hold, which surfaces as
-- "Server has closed the connection"; as decided in
-- docs/adr/postgres_pooled_idle_session_adr.md.
--
-- Idempotent. Apply as a superuser against the main-storage_postgres server:
--   psql -d postgres -v ON_ERROR_STOP=1 -f database-session-settings.sql
-- Settings apply to sessions opened after the change.

ALTER DATABASE langfuse SET idle_session_timeout = 0;
