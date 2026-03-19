# Main Stack Architecture

This directory contains the core infrastructure services for the Docker Swarm cluster.

## Services Overview

- **traefik.yml**: Reverse proxy, load balancer, SSL termination, and authentication (Traefik + Authelia)
- **storage.yml**: Database and storage services (PostgreSQL, Redis, OpenSearch, MinIO, MongoDB, InfluxDB)
- **monitoring.yml**: Observability collectors/exporters and metric adapters (Node Exporter, cAdvisor, Docker health collectors, DNS/Speed/blackbox exporters)
- **maintenance.yml**: Cluster maintenance and host reconciler services (ephemeral rebalance, rclone fixer, host sysctl baselines)
- **uptime.yml**: Human-facing status/uptime services (Gatus, Uptime Kuma)
- **bridges.yml**: Cross-system/vendor bridge services (Netdata parent bridge)
- **security.yml**: Security monitoring and threat detection (CrowdSec)

## Monitoring vs Uptime Semantics

1. `monitoring.yml` is for telemetry collection/export pipelines consumed by Prometheus/Grafana.
2. `uptime.yml` is for operator-facing uptime/status interfaces.
3. Uptime-related metrics can be collected in monitoring while still being presented in uptime tools.

## Traefik Architecture

### Entrypoints

| Entrypoint | Port | Protocol | Purpose | Access Level |
|------------|------|----------|---------|--------------|
| `web` | 80 | HTTP | Redirects to HTTPS | Public |
| `websecure` | 443 | HTTPS | Web interfaces and HTTP APIs | VPN/Internal |
| `host-internal` | Custom | TCP/TLS | Database protocols and custom services | VPN/Internal |
| `dns` | 53 | TCP/UDP | DNS services | Internal |

### Network Segmentation

#### `traefik-public` Network
- **Purpose**: External access through Traefik
- **Usage**: Services that need to be accessible via web browsers or HTTP clients
- **Security**: VPN-protected, not internet-exposed

#### `traefik` Network
- **Purpose**: Direct cluster communication
- **Usage**: Inter-service communication within the cluster
- **Security**: Internal cluster traffic only

#### `prometheus` Network (external + attachable)
- **Purpose**: Deterministic Grafana datasource path to Prometheus
- **Usage**: `grafana -> trusted-prometheus:9090` only
- **Security**: Internal cluster traffic only
- **Why external+attachable**:
  - Reusable shared overlay across stack updates and future stack consumers
  - Avoids stack-scoped network churn (`main-traefik_prometheus`) and keeps stable network identity
  - Reduces service-discovery ambiguity from multi-network alias resolution

#### Dual Network Services
Some services use **both networks** when they need:
- Internal cluster communication (`traefik` network)
- External access through Traefik (`traefik-public` network)

**Examples:**
- `postgres`: Database protocol access + potential external tools
- `mongo-express`: Connects to MongoDB internally + serves web interface externally

## Service Configuration Patterns

### HTTP/HTTPS Services → `websecure` entrypoint

```yaml
networks:
  - traefik-public  # For external access
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.service-name.rule=Host(`service.${LOCAL_DOMAIN}`)"
  - "traefik.http.routers.service-name.entrypoints=websecure"
  - "traefik.http.routers.service-name.tls=true"
  - "traefik.http.routers.service-name.tls.certresolver=le-dns"
  - "traefik.http.services.service-name.loadbalancer.server.port=8080"
  - "traefik.swarm.network=traefik-public"
```

### Database/Protocol Services → `host-internal` entrypoint

```yaml
networks:
  - traefik  # For internal cluster access
labels:
  - "traefik.enable=true"
  - "traefik.tcp.routers.service-name.rule=HostSNI(`service.${LOCAL_DOMAIN}`)"
  - "traefik.tcp.routers.service-name.entrypoints=host-internal"
  - "traefik.tcp.routers.service-name.tls=true"
  - "traefik.tcp.routers.service-name.tls.certresolver=le-dns"
  - "traefik.tcp.services.service-name.loadbalancer.server.port=5432"
  - "traefik.swarm.network=traefik"
```

## Service Decision Matrix

| Service Type | Protocol | Entrypoint | Network(s) | Example |
|--------------|----------|------------|------------|---------|
| Web Interface | HTTP/HTTPS | `websecure` | `traefik-public` | OpenSearch Dashboards |
| REST API | HTTP/HTTPS | `websecure` | `traefik-public` | OpenSearch API |
| Database | Custom Protocol | `host-internal` | `traefik` | PostgreSQL, Redis |
| Admin Tool | HTTP/HTTPS | `websecure` | `traefik-public` + `traefik` | Mongo Express |
| Metrics Datasource | HTTP/HTTPS | None (internal path) | `prometheus` | Grafana -> trusted-prometheus |
| Internal Only | N/A | None | `traefik` | InfluxDB |

## Environment Variables

- `${LOCAL_DOMAIN}`: Internal domain for VPN-accessible services
- `${DOMAIN_NAME}`: External domain (used sparingly for truly public services)
- `${INTERNAL_PORT}`: Port for host-internal entrypoint (default: 5578)

## Security Notes

- All entrypoints are VPN-protected, not internet-exposed
- `host-internal` provides additional restriction for infrastructure services
- Network segmentation prevents unnecessary cross-ser vice communication
- TLS termination handled by Traefik with Let's Encrypt certificates

## Troubleshooting

### Service Not Accessible
1. Check if service is on correct network for its entrypoint
2. Verify `traefik.swarm.network` matches the entrypoint's expected network
3. Ensure `HostSNI()` is used for TCP services, `Host()` for HTTP services

### Internal Communication Issues
1. Verify both services are on `traefik` network
2. Check if service needs to access another service's protocol port
3. Consider if service needs dual network configuration
