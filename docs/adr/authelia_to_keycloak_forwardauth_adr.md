# Authelia to Keycloak forwardAuth migration

Status: implemented and Authelia retired 2026-10-13. Six routes use oauth2-proxy forwardAuth, Grafana uses native Keycloak login (Gabriel confirmed a real login), and the four Authelia services are scaled to zero.

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
- **Authelia gate removed from the web route (2026-10-13, applied live and persisted in the compose file):** `grafana-web` no longer carries `authelia@swarm`, so Grafana's own login page is the gate. Remaining controls: self sign-up is disabled (`GF_USERS_ALLOW_SIGN_UP=false`), Google login admits only existing accounts (`GF_AUTH_GOOGLE_ALLOW_SIGN_UP=false`, domain `gmail.com`), Keycloak login requires group `admin` or `mlflow-admin` (strict role mapping), and the local admin account remains. The `/api` router was already unauthenticated by design. The trade-off is that the Grafana login form is reachable without a prior Authelia prompt on the tailnet.
- **Insecure e-mail lookup (2026-10-13, applied live and persisted):** `GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP=true`. Gabriel's first Keycloak login failed with "user sync failed / unable to create user: user not found" because his Keycloak user (same e-mail) maps to a Grafana account created earlier through Google, and Grafana does not link accounts by e-mail without this flag. Risk: any OAuth provider that can assert an e-mail can take over the matching account. Accepted because the only generic_oauth IdP is our own Keycloak realm `sigilcore`, access is limited to the groups above and Google admits only existing accounts. Mitigation: keep e-mail verification required for users in `sigilcore` (Grafana does not check `email_verified` itself), and drop the flag once accounts are linked (the linked login keeps working through the stored auth id).

### Login check and retirement (2026-10-13)

Gabriel logged in through Grafana with Keycloak (<operator-email>) and Grafana opened. A search of every Swarm service's labels and environment and of the Traefik file configuration found no remaining reference to the `authelia` middleware or the verify endpoint. The only textual remnants are `stacks/ml/orchestration.yml` (`metaflow-ui`, not deployed) and the Authelia service's own labels in `stacks/main/traefik.yml`; migrate `metaflow-ui` to the oauth2-proxy pattern before deploying it.

Replica counts before: authelia 3, authelia-redis 1, authelia-db 1, authelia-db-backup 1 (authelia-users 0). Last logs, service specs and a fresh `pg_dump` (custom format) of the `authelia` database were saved on fardustdev under `~/authelia-migration-rollback/retire/` of the operator account. The latest scheduled dump (`PG_authelia.12-October-2026.dmp`, 2026-10-12 23:30 UTC) was readable with `pg_restore -l`. The four services were then scaled to 0 and their `replicas:` in the compose files set to 0 so a redeploy does not bring them back. Volumes (`main-traefik_authelia-data`, `-configs`, `-redis-config`, the backup volume) and all backups were left in place.

Restore: set the `replicas:` values back in `stacks/main/traefik.yml` and `stacks/main/maintenance.yml`, then `docker service scale main-traefik_authelia-db=1 main-traefik_authelia-redis=1`, wait for both to be healthy, `docker service scale main-traefik_authelia=3 main-maintenance_authelia-db-backup=1`, and re-add the `authelia@swarm` middleware label on the routes that should use it. The final dump restores with `pg_restore` into an empty `authelia` database.

## Alternatives

- Reuse the shared `oauth2-proxy-forward-auth@swarm` middleware from `logging.yml`: rejected, it does not forward `Cookie`, so browser sessions would not authenticate.
- Second oauth2-proxy for `.tralmor.com` plus a Keycloak redirect URI: more infrastructure and a change to a shared client; rejected in favor of Grafana native OIDC.
- Drop Authelia from Grafana and rely on Grafana's Google login: reduces protection.
- Scale Authelia to zero now: rejected, Grafana would lose its forwardAuth target.

## Consequences

- Access to the six routes is limited to Keycloak groups `admin` and `mlflow-admin` (oauth2-proxy `allowed_groups`).
- Authelia, authelia-redis, authelia-db and authelia-db-backup run at 0 replicas with volumes and backups kept; see the restore steps above.
- Deploying `stirling-pdf` from the compose file raised it from 0 to 1 replica (Sablier normally keeps it at 0).

## Verification

Per route: `curl` shows 302 to the Keycloak `sigilcore` realm authorization endpoint (was 302 to `auth.tralmor.com`), and the Brave debug browser lands on the Keycloak sign-in page. Completing the login and exercising each UI needs a Keycloak credential and remains an operator step. Rollback: redeploy the previous compose file (`git revert` of the migration commit, then `uv run cluster-utils deploy service <name>`).
