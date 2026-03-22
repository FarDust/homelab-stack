# Productivity Stack

This directory contains user-facing productivity and personal management services for the Docker Swarm cluster.

## Scope (what belongs in `stacks/productivity/`)

- **Belongs here:** **End-user productivity** and personal management software (finance, automation, general tools, browser labs) that household members use day to day, distinct from shared platform services and from database admin consoles.
- **Add a compose file here** when the service is a **productivity or lifestyle app** (web UI or API) deployed as its own stack, not as part of edge routing or shared storage compose files.

## Services Overview

- **tools.yml**: General productivity tools and utilities for end users.
- **finance.yml**: Personal finance management and accounting (e.g., Firefly III).
- **automations.yml**: Workflow automation (n8n) with an in-stack Redis queue for Bull/worker use; connects to Postgres and optional S3/MinIO per env.
- **browser-lab.yml**: Remote browser lab (Neko + Brave) for GPU-accelerated streaming behind Traefik.

## Architecture Principles

- **Separation of Concerns**: Productivity services are distinct from core infrastructure and admin interfaces.
- **Network Assignment**: Services use `traefik-public` for external (VPN) access and private overlays for internal communication.
- **Security**: No sensitive data or secrets are tracked in git. All secrets are referenced from `../../secrets/` and must be managed outside of version control.
- **Naming Convention**: Stack files follow the `<folder>-<filename>` pattern for clarity and to avoid conflicts (see [AGENTS.md](../../AGENTS.md)).

## File Structure

```
stacks/productivity/
├── tools.yml           # General productivity tools
├── finance.yml         # Personal finance management
├── automations.yml     # n8n automation + queue Redis
├── browser-lab.yml     # Neko browser lab
├── configs/            # Service configurations
├── secrets/            # Secret file references (not tracked in git)
└── README.md           # This documentation
```

## Deployment

From the **repository root**:

1. Load env: `set -a; source .env; set +a`
2. Deploy using cluster utilities (canonical): `uv run cluster-utils deploy --help`

Swarm **stack names** follow `productivity-<filename>` (no `.yml`), for example:

| Compose file | Stack name |
|--------------|------------|
| `stacks/productivity/tools.yml` | `productivity-tools` |
| `stacks/productivity/finance.yml` | `productivity-finance` |
| `stacks/productivity/automations.yml` | `productivity-automations` |
| `stacks/productivity/browser-lab.yml` | `productivity-browser-lab` |

Ensure all referenced secrets and configs exist before deploying.

## Security Notice

- **No sensitive data is committed to this repository.**
- All secrets (e.g., Firefly III app keys) are referenced from the `secrets/` directory and must be managed securely.
