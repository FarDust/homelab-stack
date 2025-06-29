# Retrieval Stack Architecture

This directory contains data retrieval and query API services for the Docker Swarm cluster.

## Services Overview

- **analytics.yml**: Business intelligence and analytics query APIs (CubeJS)
- **documents.yml**: Document intelligence and retrieval APIs (RAGFlow)

## Retrieval Service Types

### Business Intelligence APIs
- **Purpose**: Provide semantic layer over existing databases for analytics queries
- **Pattern**: SQL-to-API transformation with caching and aggregation
- **Use Cases**: Business dashboards, reporting APIs, metrics aggregation
- **Integration**: Connects to PostgreSQL, Redis, and other data sources

### Document Intelligence APIs
- **Purpose**: Make documents searchable and retrievable through AI-powered APIs
- **Pattern**: Document ingestion, processing, and intelligent retrieval
- **Use Cases**: RAG workflows, document search, content analysis
- **Integration**: Vector search, LLM workflows, web scraping

## Service Characteristics

### API-First Architecture
All retrieval services are designed as **backend APIs** that applications consume:
- RESTful interfaces for data access
- GraphQL endpoints for flexible querying
- WebSocket APIs for real-time data streams
- Authentication and rate limiting

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

| Service Type | Data Sources | API Pattern | Access Level | Example |
|--------------|--------------|-------------|--------------|---------|
| Analytics API | SQL Databases | REST/GraphQL | Internal | CubeJS metrics API |
| Document API | File Storage + Vector DB | REST + Streaming | Internal + External | RAGFlow search API |
| Search API | Search Indexes | REST + WebSocket | Internal | Elasticsearch API |
| Feature API | Feature Stores | REST + gRPC | Internal | ML feature serving |

## Integration Patterns

### With Storage Layer (main/storage)
- **PostgreSQL**: Business data queries and analytics
- **MongoDB**: Document metadata and collections
- **Redis**: Query caching and session storage
- **OpenSearch**: Full-text search and vector retrieval
- **MinIO**: Document and asset storage

### With Application Layer
- **LLM Services**: RAG workflows and document intelligence
- **Productivity Tools**: Business intelligence and reporting
- **Admin Dashboards**: System metrics and monitoring data
- **Custom Applications**: API integration and data access

## Environment Variables

- `${LOCAL_DOMAIN}`: Internal domain for retrieval service APIs
- `${ANALYTICS_CACHE_TTL}`: Cache duration for analytics queries
- `${DOCUMENT_PROCESSING_TIMEOUT}`: Timeout for document processing jobs
- `${MAX_QUERY_COMPLEXITY}`: Limit for complex analytical queries

## Security Notes

- Retrieval services are **API-focused**, not user-facing dashboards
- **Internal access** by default - applications consume these APIs
- **Authentication required** for external document upload endpoints
- **Rate limiting** prevents query abuse and resource exhaustion
- **Data masking** for sensitive information in analytics APIs

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
