# ADR: Grafana queries Loki directly on the overlay network

Date: 2026-10-13 06:30 UTC

## Context

Grafana reported "Authentication to data source failed" for the Loki datasource (uid `P8E80F9AEF21F6940`) from 2026-10-12 evening until 2026-10-13 06:11 UTC.

The datasource pointed at the routed endpoint `https://loki.<domain>`, which sits behind Traefik forwardAuth and oauth2-proxy. It authenticated with a Keycloak `client_credentials` bearer (`loki-api`) that expires after 300 seconds. A helper service, `main-logging_grafana-loki-token-refresh`, minted a token every 240 seconds and rewrote the datasource header through the Grafana API.

Evidence gathered on 2026-10-13 (credential-safe):

- The refresher task (frost-fang, started 2026-10-12 20:28 UTC) logged `HTTP Error 404`, then `502`, then `<urlopen error timed out>` roughly every 30 seconds for 9 hours (765 timeouts).
- From inside the refresher container, Keycloak answered (`200`, `expires_in=300`, token length 1357) while a TCP connect to Grafana's task address `198.51.100.10:3000` timed out. Grafana had moved to fardustdev 24 hours earlier, so the refresher (frost-fang) reached it across the VXLAN overlay.
- Other cross-node flows from the same container (Traefik, Keycloak) worked at the same time, the neighbor and FDB entries for the Grafana task were correct on both nodes, and `tcpdump` showed healthy VXLAN traffic. At 06:11:52 UTC the next attempt succeeded with no change made by us. The exact packet-level cause of the 9 hour connect timeout is therefore not proven. The window coincides with the frost-fang I/O stall and the 2026-10-12 recovery cascade (`memberlist` join timeouts and neighbor entry churn are in the Docker journal at 20:30 UTC).
- Without a refresh the bearer expired 5 minutes after the last success, so oauth2-proxy returned 401 and Grafana reported the authentication failure.

Root cause: a five-hop authentication chain (refresher, Keycloak, Grafana API, Traefik, oauth2-proxy) with a 5 minute credential lifetime and no liveness signal. One stalled hop (the refresher's overlay connection to Grafana) looked like a datasource authentication error 9 hours later, and the refresher kept retrying silently inside a `while True` loop.

## Decision

Point the Grafana Loki datasource at the in-cluster address `http://loki:3100`, with no bearer header. This matches how the other consumers already reach the backends:

- Vector writes to `http://loki:3100` without authentication.
- The Prometheus datasource uses `http://trusted-prometheus:9090`.
- Loki runs with `auth_enabled: false` and is exposed to humans only through the oauth2-proxy route.

Remove the refresher service and its config from `stacks/main/logging.yml`. Keep the Keycloak client `loki-api` and the oauth2-proxy route for human and API access through Traefik.

## Alternatives

1. Keep the design and add a healthcheck plus restart on a stale token. Rejected: it keeps five dependencies and a 5 minute lifetime for traffic that never leaves the overlay.
2. Run the refresher on the same node as Grafana. Rejected: it needs a hostname pin or a new label, and it only narrows the failure window.
3. Lengthen the token lifetime in Keycloak. Rejected: still a moving credential with no liveness signal.

## Consequences

- Grafana no longer depends on Keycloak, Traefik, oauth2-proxy or a token refresher to read logs.
- Anything on the `traefik` overlay network can read Loki, as it already could write to it. Grafana's own datasource permissions remain the access control for humans.
- The Grafana database still holds the last expired bearer in the datasource's `secureJsonData` (provisioning does not clear fields it no longer declares). Loki ignores it. Saving the datasource in the UI clears it.
- `scripts/tests/test-grafana-loki-auth.sh` still checks the Keycloak claim contract and the Grafana datasource proxy, which remain valid for the routed endpoint.

## Verification

- `mcp-grafana get_datasource` shows `url=http://loki:3100` at version 2.
- `query_loki_logs` returned recent `main-logging_loki` lines through Grafana after the redeploy.
- Rollback: `git revert` the commit, bump `GRAFANA_CONFIG_VERSION`, redeploy `grafana` from `stacks/main/traefik.yml`, and redeploy `grafana-loki-token-refresh` from `stacks/main/logging.yml` (the revert restores both).
