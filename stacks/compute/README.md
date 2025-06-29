# Compute Stack Architecture

This directory contains execution environment services for the Docker Swarm cluster.

## Services Overview

- **execution.yml**: Code execution environments and sandbox services (Sandbox Executor Manager)

## Execution Environment Types

### Code Sandbox Execution
- **Purpose**: Secure execution of user-submitted code in isolated containers
- **Supported Languages**: Python, Node.js (configurable base images)
- **Use Cases**: LLM code generation, interactive notebooks, API code execution
- **Security**: Memory limits, timeouts, seccomp profiles, container isolation

## Hardware Constraint Patterns

Execution services use Docker Swarm node labels for placement:

### Common Label Patterns
```yaml
placement:
  constraints:
    - node.role == manager                    # Manager nodes (standard pattern)
    - node.labels.swarm.leader == true        # Swarm leader specifically
    - node.labels.AVX != false               # AVX CPU support required
    - node.labels.gpu == true                # GPU access required
    - node.labels.gpu == false               # CPU-only execution
    - node.labels.storage.manager == true    # High-performance storage
```

## Service Configuration Patterns

### Execution API Services → `websecure` entrypoint

```yaml
networks:
  - traefik-public  # External API access
  - traefik         # Internal cluster communication
labels:
  - "traefik.http.routers.execution.rule=Host(`execution.${LOCAL_DOMAIN}`)"
  - "traefik.http.routers.execution.entrypoints=websecure"
```

### Container Management Services

Services that create/destroy execution containers require:
- `privileged: true` access
- Docker socket mount (`/var/run/docker.sock`)
- Security constraints (`no-new-privileges:true`)
- Resource limits (memory, timeouts)

## Service Decision Matrix

| Service Type | Purpose | Networks | Access Level |
|--------------|---------|----------|--------------|
| Execution API | Code submission & results | `traefik-public` + `traefik` | VPN/Internal |
| Container Manager | Sandbox orchestration | `traefik` | Internal Only |
| Base Images | Execution environments | None | Internal Only |

## Environment Variables

- `${LOCAL_DOMAIN}`: Internal domain for execution service APIs
- `${EXECUTION_POOL_SIZE}`: Concurrent execution container limit
- `${EXECUTION_MAX_MEMORY}`: Memory limit per execution container
- `${EXECUTION_TIMEOUT}`: Maximum execution time

## Security Notes

- Execution services are VPN-protected, not internet-exposed
- Container isolation prevents code escape to host system
- Resource limits prevent DoS attacks through resource exhaustion
- Privileged access limited to container management services only

## Troubleshooting

### Service Won't Start
1. Verify Docker socket access for container management services
2. Check node label constraints match available nodes
3. Ensure base images are available for execution environments

### Execution Failures
1. Check resource limits (memory, CPU, timeouts)
2. Verify base image availability and network access
3. Review container isolation and security settings
