# Keycloak is pinned to the storage-manager node

## Context

On 2026-10-12 and again on 2026-10-13 ~06:55 UTC, ephemeral-rebalance force-updated `main-identity_keycloak` after the ephemeral node (gabriel-pc-wsl) changed state. Keycloak runs `start` without `--optimized`, so every restart takes about two minutes and SSO (oauth2-proxy and every OIDC client) is down meanwhile. The service only carried `node.role == worker`, so the controller considered it movable, while its database (`keycloak-db`) and OpenBao were already pinned with `node.labels.storage.manager == true`.

## Decision

Add `node.labels.storage.manager == true` to the Keycloak placement constraints. ephemeral-rebalance already skips services pinned by a cluster-group constraint, so it no longer restarts or moves Keycloak. The change is label-based, as the cluster rules require.

## Alternatives

- Teach the controller a protected-service list by name: rejected, because movement rules are label-driven.
- Run Keycloak with `--optimized` to shorten restarts: still desirable and tracked separately; it reduces the outage, not the cause.
- Leave it movable and accept short SSO outages: rejected, because identity is a dependency of every protected route.

## Consequences

Keycloak stays on a node with the storage-manager label. If that node is down, Swarm cannot place Keycloak elsewhere, which matches its database placement.

## Verification

After a live `docker service update --constraint-add` (2026-10-13 06:58 UTC), Keycloak answered 200 on the OIDC discovery endpoint, and the controller logged "Skipping service by cluster-group constraints: main-identity_keycloak" on every pass.
