# Admin Tools Stack

This stack contains administrative interfaces and dashboards for managing storage services.

## Scope (what belongs in `stacks/admin/`)

- **Belongs here:** **Browser-based admin UIs** for data and search systems whose engines are deployed by the core storage compose file [`storage.yml`](../main/storage.yml): PostgreSQL admin, Mongo web UI, OpenSearch Dashboards, and similar.
- **Add a service here** when it is an **operator dashboard** for a datastore or search engine you already run from that storage stack, not the engine service itself.

## Architecture Philosophy

**Separation of Concerns**: This stack maintains a clear separation between:
- **Core infrastructure** (`main/` stack): Database engines, storage services, monitoring infrastructure
- **Service administration** (`admin/` stack): User interfaces for managing individual services

## Services

### Database Administration
- **pgAdmin** (`pgadmin.${LOCAL_DOMAIN}`): Web interface for PostgreSQL administration
- **Mongo Express** (`mongo-express.${LOCAL_DOMAIN}`): Web interface for MongoDB administration (with basic auth enabled)

### Search & Analytics
- **OpenSearch Dashboards** (`opensearch-dashboards.${LOCAL_DOMAIN}`): Web interface for OpenSearch cluster management and data visualization

## Security Features

- **File-based secrets**: All passwords and keys stored securely as Docker secrets
- **Basic Authentication**: Mongo Express requires username/password for web access
- **TLS Encryption**: All services use HTTPS with automatic certificates
- **Network Isolation**: Services communicate via internal Docker networks

## Network Configuration

All services use:
- **Networks**: `traefik-public` (for external access) + `traefik` (for internal service communication)
- **Entrypoint**: `websecure` (HTTP/HTTPS services)
- **TLS**: Automatic certificate generation via Let's Encrypt
- **Routing**: Standard HTTP router patterns with HTTPS redirect

## Deployment

From the **repository root**, prefer [AGENTS.md](../../AGENTS.md) deploy flow: `set -a; source .env; set +a` then `uv run cluster-utils deploy --help` (stack name **`admin-dashboards`**, compose file **`stacks/admin/dashboards.yml`**).

Equivalent raw Swarm command:

```bash
docker stack deploy -c stacks/admin/dashboards.yml admin-dashboards
docker service ls | grep admin-dashboards
```

## Dependencies

This stack depends on storage services from the `main-storage` stack:
- PostgreSQL (for PGAdmin)
- MongoDB (for Mongo Express)
- OpenSearch (for OpenSearch Dashboards)

Deploy `main-storage` before deploying this stack.
