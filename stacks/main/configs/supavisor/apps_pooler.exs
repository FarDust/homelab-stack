# Supavisor tenant seeding for the apps pooler.
# This script is run via `supavisor eval` before the server starts.
# It idempotently registers every application tenant in the _supavisor.tenants
# table so that Supavisor can proxy connections on their behalf.
# New tenants should be added here as additional services are onboarded.

Application.ensure_all_started(:supavisor)

upstream_host = System.get_env("UPSTREAM_DB_HOST", "postgres")
upstream_port = String.to_integer(System.get_env("UPSTREAM_DB_PORT", "5432"))

common_attrs = %{
  "db_host" => upstream_host,
  "db_port" => upstream_port,
  "ip_version" => "auto",
  "upstream_ssl" => false,
  "require_user" => true,
  "default_parameter_status" => %{},
  "default_pool_size" => 10,
  "default_pool_strategy" => "fifo"
}

tenants = [
  %{
    "external_id" => "grafana",
    "db_database" => System.get_env("GF_POSTGRES_DB", "grafana"),
    "users" => [
      %{
        "db_user" => "vizlord",
        "db_password" => System.get_env("GRAFANA_UPSTREAM_PASSWORD"),
        "is_manager" => true,
        "mode_type" => "transaction",
        "pool_size" => 5
      }
    ]
  },
  %{
    "external_id" => "langfuse",
    "db_database" => "langfuse",
    "users" => [
      %{
        "db_user" => "langfuse",
        "db_password" => System.get_env("LANGFUSE_UPSTREAM_PASSWORD"),
        "is_manager" => true,
        "mode_type" => "transaction",
        "pool_size" => 5
      }
    ]
  }
]

for tenant <- tenants do
  password = tenant["users"] |> List.first() |> Map.get("db_password")

  if is_nil(password) do
    IO.puts("Skipping tenant #{tenant["external_id"]}: upstream password env var not set")
  else
    case Supavisor.Tenants.get_tenant_by_external_id(tenant["external_id"]) do
      nil ->
        {:ok, _} = Supavisor.Tenants.create_tenant(Map.merge(common_attrs, tenant))
        IO.puts("Created tenant: #{tenant["external_id"]}")

      _ ->
        IO.puts("Tenant already exists, skipping: #{tenant["external_id"]}")
    end
  end
end
