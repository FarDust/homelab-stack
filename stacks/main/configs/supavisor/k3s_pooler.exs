# Supavisor tenant seeding for the K3S bridge pooler.
# This script is run via `supavisor eval` before the server starts.
# It idempotently registers the K3S cluster tenant so that Supavisor can
# proxy connections from K3S workloads to the homelab Postgres instance.

Application.ensure_all_started(:supavisor)

upstream_host = System.get_env("UPSTREAM_DB_HOST", "postgres")
upstream_port = String.to_integer(System.get_env("UPSTREAM_DB_PORT", "5432"))

k8s_password = System.get_env("ASSIMILATION_UPSTREAM_PASSWORD")
k8s_user = System.get_env("K8S_DB_USER", "k3s")
k8s_db = System.get_env("K8S_DB_NAME", "k3s")

if is_nil(k8s_password) do
  IO.puts("Skipping K3S tenant: ASSIMILATION_UPSTREAM_PASSWORD env var not set")
else
  case Supavisor.Tenants.get_tenant_by_external_id("k3s") do
    nil ->
      {:ok, _} =
        Supavisor.Tenants.create_tenant(%{
          "external_id" => "k3s",
          "db_host" => upstream_host,
          "db_port" => upstream_port,
          "db_database" => k8s_db,
          "ip_version" => "auto",
          "upstream_ssl" => false,
          "require_user" => true,
          "default_parameter_status" => %{},
          "default_pool_size" => 20,
          "default_pool_strategy" => "fifo",
          "users" => [
            %{
              "db_user" => k8s_user,
              "db_password" => k8s_password,
              "is_manager" => true,
              "mode_type" => "session",
              "pool_size" => 20
            }
          ]
        })

      IO.puts("Created tenant: k3s")

    _ ->
      IO.puts("Tenant already exists, skipping: k3s")
  end
end
