# Authelia to Keycloak forwardAuth migration

Status: partially implemented 2026-10-13 (six of seven routes moved; Grafana remains on Authelia).

## Context

Seven Traefik routers still used the `authelia` forwardAuth middleware: mongo-express, grafana (web), sablier, gatus, searxng (web), stirling-pdf and ntopng. Every other protected route (MLflow, Firefly III, Obsidian, Loki, trust-agent) uses the shared `main-identity-gateway_oauth2-proxy` backed by the Keycloak realm `sigilcore`. Authelia was kept alive only for these seven routes.

## Decision

- Move each route to the per-service oauth2-proxy forwardAuth pattern used by `stacks/productivity/knowledge.yml` (Obsidian): an `errors` middleware that rewrites the 401 into a 302 to `/oauth2/sign_in?rd={url}` plus a `forwardAuth` middleware pointing at `http://main-identity-gateway_oauth2-proxy:4180/oauth2/auth`.
- `authRequestHeaders` includes `Cookie` so browser sessions work. `authResponseHeaders` is limited to `X-Auth-Request-User` and `X-Auth-Request-Email`; these UIs are not token consumers, so the Authorization header and the access token are not forwarded to them.
- Middleware names are prefixed per router (`<router>-oauth2-errors`, `<router>-oauth2-forward-auth`) because Swarm-provider middleware names are global.
- Sablier ordering is preserved: authentication runs before `load-productivity@file` and `load-searxng@file`, so an unauthenticated request never wakes a service. The unauthenticated `searxng-api` router (`/search`) is unchanged.
- The Sablier plugin talks to `http://sablier-app:10000` over `traefik-public`; it never uses the `sablier.${LOCAL_DOMAIN}` router. That router listens on the `web` entrypoint only (HTTP redirects to HTTPS, HTTPS returns 404), so it was already unreachable. Only its middleware was swapped; the entrypoint was left unchanged.

## Grafana: not migrated

Grafana is served at `grafana.${DOMAIN_NAME}` (`grafana.tralmor.com`), outside the `.${LOCAL_DOMAIN}` cookie domain and `whitelist_domains` of the shared oauth2-proxy, and the Keycloak `oauth2-proxy` client only allows the redirect URI `https://oauth2.${LOCAL_DOMAIN}/oauth2/callback`. A working route needs a second oauth2-proxy instance (cookie domain `.tralmor.com`, its own redirect URI) plus a Keycloak client change, or Grafana's native Keycloak OIDC login. Both change the identity provider and were outside the authorization of this migration. Grafana also has its own Google OAuth login. Authelia therefore stays running until this is decided.

## Alternatives

- Reuse the shared `oauth2-proxy-forward-auth@swarm` middleware from `logging.yml`: rejected, it does not forward `Cookie`, so browser sessions would not authenticate.
- Drop Authelia from Grafana and rely on Grafana's Google login: reduces protection; needs the operator's decision.
- Scale Authelia to zero now: rejected, Grafana would lose its forwardAuth target.

## Consequences

- Access to the six routes is limited to Keycloak groups `admin` and `mlflow-admin` (oauth2-proxy `allowed_groups`).
- Authelia, authelia-redis, authelia-db and authelia-db-backup stay at their previous replica counts.
- Deploying `stirling-pdf` from the compose file raised it from 0 to 1 replica (Sablier normally keeps it at 0).

## Verification

Per route: `curl` shows 302 to the Keycloak `sigilcore` realm authorization endpoint (was 302 to `auth.tralmor.com`), and the Brave debug browser lands on the Keycloak sign-in page. Completing the login and exercising each UI needs a Keycloak credential and remains an operator step. Rollback: redeploy the previous compose file (`git revert` of the migration commit, then `uv run cluster-utils deploy service <name>`).
