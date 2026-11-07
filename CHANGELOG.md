# Changelog

## 0.1.3

- Pin Traefik to the previously deployed immutable digest so a routing-only service update cannot silently upgrade the proxy through the floating `latest` tag.

## 0.1.2

- Resolve the exact OpenBao and Keycloak TLS hostnames to Traefik's existing `trust-internal` endpoint for Trust Agent consumers. This preserves TLS/SNI and network segmentation while avoiding an unreachable container-to-local-Tailscale hairpin.

## 0.1.1

- Refresh vulnerable Python dependency locks within the existing declared constraints, including AnyIO 4.14.2, LiteLLM 1.88.6, aiohttp 3.14.3, urllib3 2.8.0, Mako 1.4.2, multidict 6.9.1, and patched HTTP, parsing, and serialization dependencies.
- Preserve the existing cryptography 46, virtualenv 20, langsmith 0.6, and langgraph-sdk 0.3 compatibility lines. Advisories requiring incompatible upgrades remain open for a separately validated migration.
- Keep the editable cluster-utils source declaration unchanged. No stack configuration, deployment, service state, or credentials are changed.
