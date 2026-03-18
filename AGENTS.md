# Agent Insights & Patterns

Quick reference for AI agents working on this infrastructure.

## Conventional Commits

Follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/): use a type (`feat`, `fix`, `docs`, `chore`, `refactor`, etc.), optional scope in parentheses, and a short description. Use two `-m` when adding body:

```bash
git commit -m "<type>[optional scope]: <very-short-description>" -m "<extra-body>"
```

Examples: `feat(monitoring): add Loki dashboard`, `fix(traefik): correct HostSNI for postgres`.

## Core Mantras
- **Keep services generic and ready-to-use**: Prefer official upstream images and runtime configuration (`configs`, env, secrets, volumes) over custom image builds. Only introduce custom images when explicitly approved for a specific stack need.

## Architecture Patterns

### Traefik Entrypoint Selection
- **HTTPS interfaces** → `websecure` entrypoint + `Host()` rule
- **Custom protocols** (postgresql://, redis://, mongodb://) → `host-internal` entrypoint + `HostSNI()` rule
- **TCP vs HTTP**: If it uses https:// URLs, use websecure. If it uses custom:// protocol, use host-internal.

### Network Assignment Rules
- **External access only**: `traefik-public` network
- **Internal cluster only**: `traefik` network
- **Both internal + external**: Both networks (don't remove `traefik` when adding `traefik-public`)

### Domain Variables
- `${LOCAL_DOMAIN}`: Internal/VPN services
- `${DOMAIN_NAME}`: External/public services (rare)

### Configuration Files
- **Docker Swarm**: Use `configs:` section, not bind mounts (e.g., `./file.toml:/path:ro`)
- **Pattern**: Define config at bottom with `${CONFIG_VERSION:-0}` versioning, reference in service
- **Example**: `configs: [source: myconf, target: /app/config.toml]`

## Service Categories

### Stack Organization
- **main/**: Core infrastructure (databases, networking, monitoring)
- **admin/**: Administrative dashboards and management interfaces
- **llms/**: Language model services and AI tooling
- **productivity/**: User-facing applications and tools

### Storage Services
- **Databases**: host-internal + HostSNI() + traefik network
- **Admin UIs**: websecure + Host() + traefik-public network (typically in admin/ stack)
- **APIs**: websecure + Host() + traefik-public network
- **Dual-purpose**: May need both networks

### Common Patterns
```yaml
# HTTP Service (API/UI)
entrypoints: websecure
rule: Host(`service.${LOCAL_DOMAIN}`)
network: traefik-public

# Database/Protocol Service
entrypoints: host-internal
rule: HostSNI(`service.${LOCAL_DOMAIN}`)
network: traefik
```

## Environment Insights

### GCP Integration
- Local LLMs + GCP services architecture
- OpenSearch preferred over Elasticsearch (licensing)
- RAGflow integration with storage services

### Security Model
- VPN-only access (no internet exposure)
- Traefik handles TLS termination
- Network segmentation for service isolation

### Container Images
- **Use only trusted images**: Official project images, or well-established maintainers already used in this repo (e.g. linuxserver, official Docker Hub orgs). Do not introduce random or unfamiliar images from the internet.
- When adding a new service, prefer the image already used elsewhere in the repo for that software, or the project’s official image. Do not switch to third-party images for convenience (e.g. to work around one image’s quirks) without explicit user approval.

## Quick Decision Trees

### New Service Configuration
1. **Protocol type?** HTTP(S) → websecure, Custom → host-internal
2. **Access needs?** External → traefik-public, Internal → traefik, Both → both networks
3. **Domain?** Internal → LOCAL_DOMAIN, Public → DOMAIN_NAME

### Troubleshooting Checklist
1. **Can't access service**: Check entrypoint matches protocol type
2. **Service can't reach another**: Check both on traefik network
3. **Wrong certificate**: Verify HostSNI() for TCP, Host() for HTTP
4. **SIGILL exit 132**: Check hardware compatibility (`node.labels.AVX != false` for CPU-dependent services)
5. **Service won't deploy**: Verify node label combinations exist (`docker node inspect <node> --format '{{.Spec.Labels}}'`)
6. **Image pull fails**: Always verify tag exists before deployment (`curl -s "https://registry.hub.docker.com/v2/repositories/org/image/tags/" | jq '.results[].name'`)

## Common Mistakes
- Using websecure for database protocols
- Removing traefik network when adding traefik-public
- Using Host() rules with host-internal entrypoint
- Using DOMAIN_NAME for internal services
- Violating `<folder>-<filename>` naming convention (causes service conflicts)
- Adding local volumes to services that use rclone without explicit permission (breaks multi-replica semantics)
- Introducing random or untrusted container images; stick to official or repo-established images

## Stack Relationships
- **main-traefik**: Core infrastructure (Traefik, networking, authentication)
- **main-storage**: Database and storage services
- **main-monitoring**: Observability and maintenance
- **admin-dashboards**: Administrative interfaces for storage services
- **productivity-tools**: User-facing tools (use websecure + LOCAL_DOMAIN)
- **llms-***: AI services (integrate with storage via protocols)

## Naming Convention
**Docker Swarm Pattern**: `<folder>-<filename>`

Examples:
- `stacks/main/traefik.yml` → deploy as `main-traefik` → services `main-traefik_*`
- `stacks/admin/dashboards.yml` → deploy as `admin-dashboards` → services `admin-dashboards_*`
- `stacks/productivity/tools.yml` → deploy as `productivity-tools` → services `productivity-tools_*`

Deploy command: `uv run cluster-utils deploy --help`
Exception: Use default detach behavior for stacks with sidecars that die after deploy (e.g., traefik.yml)

## File Structure Patterns
```
stacks/[stack]/
├── [stack].yml          # Main compose file
├── configs/             # Service configurations
├── secrets/             # Secret file references
└── README.md           # Stack-specific documentation
```

## Secret Management
- Secrets stored in `secrets/[service]/` directories
- Referenced in compose files with relative paths: `../../secrets/service/secret_file`
- Use `_FILE` environment variables for file-based secrets when supported by containers
- Environment variable loading pattern: `export VAR=$(cat secrets/service/file | tr -d '\n')`
- Generate cryptographically secure secrets: `openssl rand -hex 32` or `openssl rand -base64 32`

## Deployment Operations
- **Always run `source .env` before any deployment**
- If Docker Swarm config errors occur, increment `CONFIG_VERSION` in `.env` (e.g., from 89 to 90)
- Config versioning resolves conflicts with existing swarm configurations
- Rollback may be temporarily deactivated on an unstable service if needed to force a corrective config or schema fix onto the live workload. This must be treated as a temporary recovery step only; restore the standard rollback policy after the service is stable again.
- **Never skip verifications** (tests, checks, or validation steps); if a verification cannot be run, state why and provide the exact alternative confirmation performed.

## Collaboration in No-TTY Environments
- **Use tmux as the shared TTY** for interactive steps (GPG passphrase, prompts).
- **Run commands inside the tmux pane**, not from a non-TTY shell.
- **Set `GPG_TTY` to the tmux pane TTY** before signing:
  - `export GPG_TTY=$(tmux display-message -p -t <session> '#{pane_tty}')`
- **Workflow**: agent triggers command inside tmux → user attaches, enters passphrase → user detaches → agent verifies output and closes session.

## Volume Naming
- Pattern: `servicename_data` for data volumes
- Local driver for simple volumes
- Named volumes for persistence across container recreations

## Key Architectural Decisions

### Core vs Admin Separation
- **Core infrastructure monitoring** (Grafana/Prometheus) stays in `main/` - it monitors the entire homelab
- **Service-specific admin interfaces** go in `admin/` - they manage individual services
- This maintains clear separation between infrastructure health and service administration

### Database Protocol Access
- PostgreSQL, MongoDB, Redis use `host-internal` entrypoint for native protocol access
- Applications connect using standard connection strings (postgresql://, mongodb://, redis://)
- Admin web interfaces use `websecure` for browser access

### Homelab Context
- Grafana/Prometheus are core infrastructure monitoring, not admin tools
- They monitor Docker hosts, containers, network health across all stacks
- Service-specific dashboards (PGAdmin, Mongo Express) belong in admin/ stack
