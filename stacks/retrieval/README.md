# Retrieval Stack Architecture

This directory contains data retrieval and query API services for the Docker Swarm cluster.

## Scope (what belongs in `stacks/retrieval/`)

- **Belongs here:** **Query and retrieval APIs**: analytics (Cube), document/RAG (RAGFlow), **web crawling/scraping** (Firecrawl), and similar **data-plane HTTP services** that consume backing stores you run elsewhere (configure connection strings in each compose file).
- **Add a compose file here** when the workload is primarily **serving queries, documents, or crawl jobs** for other consumers, not a general-purpose end-user portal.

## Services Overview

- **analytics.yml**: Business intelligence and analytics query APIs (CubeJS).
- **documents.yml**: Document intelligence and retrieval APIs (RAGFlow).
- **web.yml**: Firecrawl (API, worker, Playwright-related URLs) behind Traefik.

Each compose file defines its own Traefik labels, networks, and dependencies; treat the details below as patterns, not a guarantee for every service.

## Retrieval Service Types

### Business Intelligence APIs
- **Purpose**: Provide a semantic layer over existing databases for analytics queries.
- **Pattern**: SQL-to-API transformation with caching and aggregation (as implemented by each upstream).
- **Use Cases**: Business dashboards, reporting APIs, metrics aggregation.
- **Integration**: Typically PostgreSQL, Redis, and other data sources you configure in env.

### Document Intelligence APIs
- **Purpose**: Make documents searchable and retrievable through application APIs.
- **Pattern**: Document ingestion, processing, and retrieval (per upstream).
- **Use Cases**: RAG-style workflows, document search, content analysis.
- **Integration**: Vector search, optional model pipelines, web scraping as configured.

## Service Characteristics

### API-First Architecture
These stacks are **backend APIs** that applications consume. Exposed protocols depend on the upstream image and your labels (often REST; see each compose file for HTTP vs WebSocket).

### Query Layer Pattern
Retrieval services act as an **intelligent middleware layer**:
- **Above storage**: Don't store data, query existing sources
- **Below applications**: Provide APIs for apps to consume
- **Semantic abstraction**: Hide storage complexity from applications
- **Performance optimization**: Caching, indexing, query optimization

## Architecture Patterns

### Database Query Services → Internal APIs

```yaml
networks:
  - traefik  # Internal cluster access for apps
labels:
  - "traefik.http.routers.analytics-api.rule=Host(`analytics.${LOCAL_DOMAIN}`)"
  - "traefik.http.routers.analytics-api.entrypoints=websecure"
```

### Document Processing Services → External + Internal APIs

```yaml
networks:
  - traefik-public  # External access for document upload
  - traefik         # Internal cluster access for apps
labels:
  - "traefik.http.routers.documents-api.rule=Host(`documents.${LOCAL_DOMAIN}`)"
  - "traefik.http.routers.documents-api.entrypoints=websecure"
```

## Service Decision Matrix

| Service Type | Data Sources | API pattern (typical) | Access level | Example in this stack |
|--------------|--------------|----------------------|--------------|------------------------|
| Analytics API | SQL databases | REST (Cube) | Internal/VPN | `analytics.yml` |
| Document API | Object storage, OpenSearch, Postgres | REST (RAGFlow) | As labeled | `documents.yml` |
| Crawl API | Redis, optional external APIs | REST (Firecrawl) | As labeled | `web.yml` |

## Integration Patterns

### With backing stores
- **PostgreSQL**: Business data queries and analytics
- **MongoDB**: Document metadata and collections
- **Redis**: Query caching and session storage
- **OpenSearch**: Full-text search and vector retrieval
- **MinIO**: Document and asset storage

Point connection strings at instances you already run from the core storage compose file (or other Postgres/Redis you manage).

### With clients
- **Downstream apps and jobs**: RAG, analytics, or automation that call these APIs
- **Custom integrations**: Any client with network access and credentials you configure

## Environment Variables

Use **`${LOCAL_DOMAIN}`** where Traefik labels reference hostnames. Everything else is **per compose file** (for example `RAGFLOW_*` in `documents.yml`, `FIRECRAWL_*` and related keys in `web.yml`, and Cube settings in `analytics.yml`). Read the `*.yml` files and `.env.example` at the repo root for the authoritative list.

## Security Notes

- Retrieval services are **API-focused**, not user-facing dashboards
- **Internal access** by default - applications consume these APIs
- **Authentication required** for external document upload endpoints
- **Rate limiting** prevents query abuse and resource exhaustion
- **Data masking** for sensitive information in analytics APIs

## Deploy

Swarm names: **`retrieval-analytics`**, **`retrieval-documents`**, **`retrieval-web`**. From the repo root: `set -a; source .env; set +a` then `uv run cluster-utils deploy --help` (see [AGENTS.md](../../AGENTS.md)).

## Troubleshooting

### Service Won't Start
1. Check database connectivity to source systems
2. Verify API authentication credentials and secrets
3. Ensure sufficient memory for query processing and caching

### Query Performance Issues
1. Review query complexity and add appropriate indexes
2. Check cache hit rates and adjust TTL settings
3. Monitor database connection pool usage
4. Consider query result pagination for large datasets

### Integration Failures
1. Verify network connectivity between retrieval and storage services
2. Check API endpoint availability and response formats
3. Review authentication tokens and service permissions
4. Monitor request/response logs for integration errors
