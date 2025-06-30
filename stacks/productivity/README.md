# Productivity Stack

This directory contains user-facing productivity and personal management services for the Docker Swarm cluster.

## Services Overview

- **tools.yml**: General productivity tools and utilities for end users.
- **finance.yml**: Personal finance management and accounting (e.g., Firefly III).

## Architecture Principles

- **Separation of Concerns**: Productivity services are distinct from core infrastructure and admin interfaces.
- **Network Assignment**: Services use `traefik-public` for external (VPN) access and private overlays for internal communication.
- **Security**: No sensitive data or secrets are tracked in git. All secrets are referenced from `../../secrets/` and must be managed outside of version control.
- **Naming Convention**: Stack files follow the `<folder>-<filename>` pattern for clarity and to avoid conflicts.

## File Structure
```
stacks/productivity/
├── tools.yml           # General productivity tools
├── finance.yml         # Personal finance management
├── configs/            # Service configurations
├── secrets/            # Secret file references (not tracked in git)
└── README.md           # This documentation
```

## Deployment
- Always run `source .env` before deploying any stack.
- Use `docker stack deploy -c <filename>.yml productivity-<filename>` for deployment.
- Ensure all referenced secrets/configs exist before deploying.

## Security Notice
- **No sensitive data is committed to this repository.**
- All secrets (e.g., Firefly III app keys) are referenced from the `secrets/` directory and must be managed securely.
