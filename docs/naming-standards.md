# Naming Standards

## Docker Swarm stacks
Pattern: `<folder>-<filename>`

| File | Stack name | Service prefix |
|------|-----------|----------------|
| `stacks/main/identity.yml` | `main-identity` | `main-identity_keycloak`, `main-identity_keycloak-db`, `main-identity_vault` |
| `stacks/main/trust-agent.yml` | `main-trust-agent` | `main-trust-agent_trust-agent`, `main-trust-agent_cluster-utils-mcp` |

## Agent applications (`agents/`)
Pattern: `agents/{kebab-case-name}/`

- Gitignored, own git repo per agent
- Kebab-case name matches the Swarm service name
- Parallel to `cluster-utils/` (library) and `services/` (config helpers)

Examples:
- `agents/trust-agent/` → Swarm stack `main-trust-agent` → services `main-trust-agent_*`

## OpenBao KV secret paths
Pattern: `secret/{service-name}/{type}`

| Type | Contents |
|------|----------|
| `api` | Runtime secrets (DB URLs, API keys, credentials) |
| `config` | Non-secret configuration values |
| `certs` | TLS certificates and keys |

Examples:
- `secret/tourism-rates/api`
- `secret/trust-agent/config`

## Keycloak realms

| Realm | Purpose |
|-------|---------|
| `master` | Admin operations only — never used for app auth |
| `${KEYCLOAK_REALM}` | Human-facing SSO (browser login) |
| `cluster-services` | Service-to-service machine identity — clients use service accounts, no login UI |

## Isolated overlay networks
Pattern: `{service-name}-internal`

Shared only with Traefik. Traefik proxies via `traefik.swarm.network` label.
Use for high-privilege services that must not be directly reachable by other app services on `traefik-public`.

Examples:
- `trust-internal` → isolates `trust-agent` from `traefik-public` peers

## Volumes
Pattern: `{servicename}_data`
Driver: `local` for simple persistence, `rclone` for GCS-backed persistence.

## Filesystem secrets
Pattern: `secrets/{service}/{secret-name}`
Referenced in compose files: `../../secrets/{service}/{file}`
