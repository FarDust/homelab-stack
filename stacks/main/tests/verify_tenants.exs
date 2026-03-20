# CI-only integration test – verifies that both pooler seed scripts actually
# write the expected rows to _supavisor.tenants and _supavisor.users.
#
# Called by the 'verifier' service in supavisor-seed.yml after the
# 'seed-runner' service has completed the migrate + eval sequence.
#
# Runs as a supavisor eval so that it uses the same Erlang DNS resolver
# that the seed scripts use (avoids musl-libc DNS quirks in Alpine images).
#
# Expected tenants after both seed scripts have run:
#   k3s      – seeded by k3s_pooler.exs
#   grafana  – seeded by apps_pooler.exs
#   langfuse – seeded by apps_pooler.exs

Application.ensure_all_started(:supavisor)

expected = Enum.sort(["k3s", "grafana", "langfuse"])

# ── verify _supavisor.tenants ───────────────────────────────────────────────
{:ok, result} =
  Supavisor.Repo.query(
    "SELECT external_id FROM _supavisor.tenants WHERE external_id = ANY($1) ORDER BY external_id",
    [expected]
  )

found = Enum.map(result.rows, fn [id] -> id end)
missing = expected -- found

if missing != [] do
  IO.puts("❌ Missing tenants in _supavisor.tenants: #{inspect(missing)}")
  IO.puts("   Found: #{inspect(found)}")
  System.halt(1)
end

Enum.each(found, fn id -> IO.puts("✅ tenant '#{id}' present in _supavisor.tenants") end)

# ── verify _supavisor.users ─────────────────────────────────────────────────
{:ok, users_result} =
  Supavisor.Repo.query(
    "SELECT DISTINCT tenant_external_id FROM _supavisor.users WHERE tenant_external_id = ANY($1) ORDER BY tenant_external_id",
    [expected]
  )

found_users = Enum.map(users_result.rows, fn [id] -> id end)
missing_users = expected -- found_users

if missing_users != [] do
  IO.puts("❌ No user records for tenants: #{inspect(missing_users)}")
  System.halt(1)
end

Enum.each(found_users, fn id -> IO.puts("✅ user record(s) for tenant '#{id}' present in _supavisor.users") end)

IO.puts("✅ All expected tenants and user records are present in the database")
