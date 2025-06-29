# Admin Tools Stack

This stack contains administrative interfaces and dashboards for managing storage services.

## Architecture Philosophy

**Separation of Concerns**: This stack maintains a clear separation between:
- **Core infrastructure** (`main/` stack): Database engines, storage services, monitoring infrastructure
- **Service administration** (`admin/` stack): User interfaces for managing individual services

## Services

### Database Administration
- **PGAdmin4** (`pgadmin.${LOCAL_DOMAIN}`): Web interface for PostgreSQL administration
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

```bash
# Deploy the admin dashboards stack
docker stack deploy -c dashboards.yml admin-dashboards

# Check status
docker service ls | grep admin-dashboards
```

## Dependencies

This stack depends on storage services from the `main-storage` stack:
- PostgreSQL (for PGAdmin)
- MongoDB (for Mongo Express)
- OpenSearch (for OpenSearch Dashboards)

Deploy `main-storage` before deploying this stack.
