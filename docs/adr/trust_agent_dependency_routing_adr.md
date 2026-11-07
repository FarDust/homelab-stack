# ADR: Route Trust Agent identity and custody dependencies through its Traefik overlay

## Context

Trust Agent is isolated on `trust-internal`, which it shares only with Traefik and
the stack's cluster-utils MCP service. Its canonical OpenBao and Keycloak URLs use
TLS hostnames. External DNS resolves those names to the manager's Tailscale address.
From a `trust-internal` task, TCP connections to that local Tailscale address can
time out even while the manager host itself reaches the same endpoints.

The same task reaches Traefik's existing `trust-internal` VIP immediately. A
read-only probe that connected to that VIP while preserving the canonical TLS SNI
and HTTP Host header completed certificate-verified TLS 1.3 and reached both
OpenBao and Keycloak routes. OpenBao seal state remains an independent dependency.

## Decision

Give the Traefik service exact `vault.${LOCAL_DOMAIN}` and `idp.${LOCAL_DOMAIN}`
aliases on its existing `trust-internal` attachment. Docker's embedded DNS then
resolves those names to Traefik inside the isolated overlay. The application keeps
the canonical HTTPS URLs, certificate verification, SNI, Host routing, bearer
authentication and OpenBao JWT exchange unchanged.

Keep Trust Agent only on `trust-internal`. Keep OpenBao and Keycloak only on their
existing `traefik-public` attachments. Traefik remains the sole bridge between the
isolated caller and those routed services.

## Alternatives

Adding Trust Agent directly to `traefik-public` would widen its peer set. Adding
OpenBao or Keycloak to `trust-internal` would widen privileged backend reachability.
Hard-coding a Traefik VIP in `extra_hosts` would become stale if the overlay is
recreated. Increasing HTTP timeouts would not repair the unreachable hairpin.

## Consequences

Every task on `trust-internal` can resolve the two exact routed hostnames to
Traefik, but gains no direct network attachment to OpenBao or Keycloak. The aliases
depend on Traefik's existing attachment and routing labels. A Traefik service update
is required to publish the aliases; deployment and rollback remain separate from
source acceptance.

## Verification

Tests assert the exact aliases and preserve the service-network boundaries. Render
the canonical stack with required environment values and verify the aliases occur
only on Traefik's `trust-internal` attachment. After an approved deployment, verify
embedded DNS, certificate-checked TLS/SNI, OpenBao health, OIDC discovery, one
authorized custody fetch, one authorization rejection and the PostgreSQL consumer's
persisted outcome without exposing credentials.
