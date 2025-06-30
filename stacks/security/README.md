# Security Stack

This directory contains network and security infrastructure services for the Docker Swarm cluster.

## Services Overview

- **network.yml**: Network analytics and security-related services (Clickhouse, Redis, ntopng-proxy)
- **dns.yml**: DNS infrastructure and privacy services (Pi-hole, DNSCrypt, DNSCrypt-Proxy)

## Architecture Philosophy

- **Separation of Concerns**: Security and network services are isolated from core infrastructure and user-facing apps.
- **No Sensitive Data in Git**: All secrets (passwords, API keys, etc.) are referenced via Docker secrets and never committed to git.
- **Role-Oriented**: Each file is focused on a specific security or network function, avoiding catch-alls.

## Security Notes

- All secrets are stored in `../../secrets/` and referenced securely.
- No sensitive data is present in this repository.
- Network segmentation and TLS are enforced for all services.

## File Structure

```
stacks/security/
├── network.yml   # Network analytics and security
├── dns.yml       # DNS infrastructure and privacy
└── README.md     # This documentation
```
