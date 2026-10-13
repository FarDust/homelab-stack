# Authelia to Keycloak forwardAuth migration

Status: partially implemented 2026-10-13. Six routes moved; Grafana has Keycloak native login deployed but still sits behind Authelia until a real Keycloak login is verified; Authelia retirement is pending.

## Context

Seven Traefik routers still used the `authelia` forwardAuth middleware: mongo-express, grafana (web), sablier, gatus, searxng (web), stirling-pdf and ntopng. Every other protected route (MLflow, Firefly III, Obsidian, Loki, trust-agent) uses the shared `main-identity-gateway_oauth2-proxy` backed by the Keycloak realm `sigilcore`. Authelia was kept alive only for these seven routes.

## Decision

- Move each route to the per-service oauth2-proxy forwardAuth pattern used by `stacks/productivity/knowledge.yml` (Obsidian): an `errors` middleware that rewrites the 401 into a 302 to `/oauth2/sign_in?rd={url}` plus a `forwardAuth` middleware pointing at `http://main-identity-gateway_oauth2-proxy:4180/oauth2/auth`.
- `authRequestHeaders` includes `Cookie` so browser sessions work. `authResponseHeaders` is limited to `X-Auth-Request-User` and `X-Auth-Request-Email`; these UIs are not token consumers, so the Authorization header and the access token are not forwarded to them.
- Middleware names are prefixed per router (`<router>-oauth2-errors`, `<router>-oauth2-forward-auth`) because Swarm-provider middleware names are global.
- Sablier ordering is preserved: authentication runs before `load-productivity@file` and `load-searxng@file`, so an unauthenticated request never wakes a service. The unauthenticated `searxng-api` router (`/search`) is unchanged.
- The Sablier plugin talks to `http://sablier-app:10000` over `traefik-public`; it never uses the `sablier.${LOCAL_DOMAIN}` router. That router listens on the `web` entrypoint only (HTTP redirects to HTTPS, HTTPS returns 404), so it was already unreachable. Only its middleware was swapped; the entrypoint was left unchanged.

## Grafana: native Keycloak login (option 2)

Grafana is served at `grafana.${DOMAIN_NAME}` (`grafana.tralmor.com`), outside the `.${LOCAL_DOMAIN}` cookie domain and `whitelist_domains` of the shared oauth2-proxy, and the shared Keycloak client `oauth2-proxy` only allows `https://oauth2.${LOCAL_DOMAIN}/oauth2/callback`. Reusing that proxy would need a second proxy instance or a change to the shared client, so Grafana uses its own OIDC login instead (decided 2026-10-13, confirmed by Gabriel).

- Keycloak: confidential client `grafana` in realm `sigilcore`, standard flow only (no direct grants, no service account), redirect URI `https://grafana.tralmor.com/login/generic_oauth`, post-logout `https://grafana.tralmor.com/login`, a `groups-claim` group-membership mapper. Created with `uv run cluster-utils keycloak upsert-oidc-client` and `upsert-group-mapper`. The shared `oauth2-proxy` client is untouched.
- Secret: `secrets/grafana/oidc_client_secret` (git-ignored) mounted as the Docker secret `grafana_keycloak_oidc_secret` and read through `GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET__FILE`.
- Grafana (`stacks/main/traefik.yml`, commit 7c5b644): `GF_AUTH_GENERIC_OAUTH_*` with PKCE, scopes `openid email profile`, `role_attribute_strict=true` and role path `admin` -> Admin, `mlflow-admin` -> Viewer; users with neither group cannot log in. Google login and the local admin account are unchanged (break-glass).
- Verified 2026-10-13: from inside the Grafana network namespace, `/login/generic_oauth` returns 302 to the Keycloak `sigilcore` authorization endpoint with `client_id=grafana` and the exact redirect URI; Grafana reaches the issuer; `/api/health` returns 200 and the mcp-grafana datasource listing still works (API router and token paths unchanged). A real Keycloak login was not performed (no credential).
- `grafana-web` still carries the `authelia@swarm` middleware. It is removed only in the final step below.

### Pending action owed by Gabriel

Sign in once through Grafana with Keycloak: open `https://grafana.tralmor.com/login` (after the Authelia prompt), choose "Sign in with Keycloak", and authenticate as a user in the Keycloak group `admin` or `mlflow-admin` that has an e-mail address. Confirm that Grafana opens with the expected role. If Keycloak reports an invalid redirect URI, the registered value is `https://grafana.tralmor.com/login/generic_oauth` on client `grafana`; do not change the shared `oauth2-proxy` client.

### Remaining one-shot checklist (after that login works)

1. Remove the line `traefik.http.routers.grafana-web.middlewares=authelia@swarm` from Grafana in `stacks/main/traefik.yml` and deploy with `uv run cluster-utils deploy service grafana` (if it fails on an immutable config name, bump `CONFIG_VERSION` first). Confirm `https://grafana.tralmor.com/` returns 302 to `/login`.
2. Confirm no service references the middleware: loop `docker service inspect` over all services and search labels for `authelia`.
3. Record replica counts (authelia 3, authelia-redis 1, authelia-db 1, authelia-db-backup 1), save the logs, then scale the four services to 0. Keep volumes and the latest backups.
4. Verify the six migrated routes and Grafana still answer, and record the result.

Rollback of Grafana OIDC: revert commit 7c5b644 and redeploy, or remove the `GF_AUTH_GENERIC_OAUTH_*` variables; the client and secret can stay.

## Alternatives

- Reuse the shared `oauth2-proxy-forward-auth@swarm` middleware from `logging.yml`: rejected, it does not forward `Cookie`, so browser sessions would not authenticate.
- Second oauth2-proxy for `.tralmor.com` plus a Keycloak redirect URI: more infrastructure and a change to a shared client; rejected in favor of Grafana native OIDC.
- Drop Authelia from Grafana and rely on Grafana's Google login: reduces protection.
- Scale Authelia to zero now: rejected, Grafana would lose its forwardAuth target.

## Consequences

- Access to the six routes is limited to Keycloak groups `admin` and `mlflow-admin` (oauth2-proxy `allowed_groups`).
- Authelia, authelia-redis, authelia-db and authelia-db-backup stay at their previous replica counts until the checklist above is complete.
- Deploying `stirling-pdf` from the compose file raised it from 0 to 1 replica (Sablier normally keeps it at 0).

## Verification

Per route: `curl` shows 302 to the Keycloak `sigilcore` realm authorization endpoint (was 302 to `auth.tralmor.com`), and the Brave debug browser lands on the Keycloak sign-in page. Completing the login and exercising each UI needs a Keycloak credential and remains an operator step. Rollback: redeploy the previous compose file (`git revert` of the migration commit, then `uv run cluster-utils deploy service <name>`).
