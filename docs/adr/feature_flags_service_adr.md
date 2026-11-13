# Cluster feature-flag service (Unleash) with an admin panel that does not take evaluation down

Status: accepted and deployed 2026-11-13 (UTC; Chile UTC-3). Stack `main-feature-flags` (`stacks/main/feature-flags.yml`),
database `unleash` on the shared PostgreSQL, break-glass CLI `tools/flags-breakglass`. Client contract (registry,
evaluation context, error envelope): the application repository's `docs/adr/feature_flags_adr.md` (Japan Route App, first
consumer).

## Context

The owner decided on 2026-11-13: "En vez de QA prefiero darme feature flags, con un panel de administración que nunca falle y
otro servicio del cluster enfocado en feature flagging. Así QA es producción y los errores deberían siempre llevar qué paths
bajo qué feature flags fallaron."

So production is the QA environment: every new feature ships behind a flag evaluated per person (the owner first, then
groups of friends), a dedicated cluster service holds the flags, its admin panel must stay usable, and every error carries
the code path and the flags that were active.

Constraints from this repository: official images pinned by digest, tailnet-only routes under `${LOCAL_DOMAIN}`, Keycloak
through the shared oauth2-proxy for admin UIs, databases created only with `cluster-utils db create-service-db`, secrets as
Swarm secrets with custody in OpenBao, placement by node labels, no spending.

## Decision

### Product: Unleash open-source edition

Counts and licences read from the GitHub API on 2026-11-13; "OSS SSO" means OIDC login for the admin UI without a paid tier.

| | Unleash | Flagsmith | GrowthBook | flagd + OpenFeature | Flipt | go-feature-flag |
| --- | --- | --- | --- | --- | --- | --- |
| Stars | 14,314 | 7,180 | 8,591 | 1,028 (CNCF) | 4,948 | 2,142 |
| Licence | AGPL-3.0 (server) | BSD-3-Clause | MIT core + commercial | Apache-2.0 | FCL-1.0-MIT (v2) | MIT |
| OIDC SSO for admin UI in OSS | no (Enterprise) | no (Enterprise; Google/GitHub OAuth only) | no (Enterprise) | no UI | yes | no real UI |
| PostgreSQL | required, native | native | MongoDB required | none (file/CRD sync) | v2: git/local only | none (retrievers) |
| TypeScript / JS SDK | first-party + OpenFeature web provider | first-party + OpenFeature | first-party + OpenFeature | OpenFeature native | OpenFeature | OpenFeature |
| Android / Kotlin | first-party SDK | first-party | first-party | OpenFeature Kotlin | client SDK | OFREP |
| Python | first-party + OpenFeature provider | first-party + OpenFeature | first-party | OpenFeature | OpenFeature | OpenFeature |
| Per-user server-side evaluation for clients | frontend API returns only that user's resolved flags | remote evaluation per identity | yes | OFREP, ruleset on server | client SDKs download the namespace | OFREP |
| Offline / last-known-good | SDK backup files, client bootstrap | offline mode | cached features | file is the source | snapshot | file |
| Admin UI | strong: projects, segments, strategies, variants, event log | good | strong (experimentation focus) | none | good | minimal |
| Per-user targeting, gradual rollout, kill switch | yes, yes (sticky), yes | yes | yes | rules in JSON | yes | yes |
| Audit log in OSS | event log | limited | yes | git history | git history | none |
| Footprint here | one Node container, PostgreSQL | API + frontend, PostgreSQL, task processor | Node + MongoDB | tiny, no UI | one Go binary | tiny |

Unleash wins on the decisive criteria: the best admin panel, native PostgreSQL (already operated and backed up), a frontend
API that evaluates on the server and returns only the caller's resolved flags (no targeting leaks to phones), first-party
SDKs in every client language and first-party OpenFeature providers (`@openfeature/unleash-web-provider`,
`openfeature-provider-unleash`, both from the OpenFeature organisation). Its OSS edition lacks OIDC SSO, so the admin UI sits
behind the cluster's oauth2-proxy + Keycloak pattern instead of paying or patching. AGPL-3.0 applies to modifications we
distribute; we run the unmodified official image. Unleash Edge (MIT) is not used: its open-source build reaches end of life on
2026-12-31 and the server's built-in frontend API covers the need.

Clients standardise on the OpenFeature API; replacing Unleash later changes one adapter per client.

### Deployment

- Image `unleashorg/unleash-server:8.3.1@sha256:025cd8b003a70cceb88427ca393c377ca6503a210d95fdee54d21610d51f7ed0`
  (index digest; amd64 `sha256:0af0f53b…`, arm64 `sha256:37352fbe…`), set through `FLAGS_UNLEASH_IMAGE`.
- Two replicas, `max_replicas_per_node: 1`, constraint `node.labels.node.ephemeral != true` (today the two stable nodes),
  `stop-first` updates one task at a time with automatic rollback (`start-first` deadlocked live on 2026-11-13: with one
  replica per node and exactly two eligible nodes the new task had no node; the other replica serves during the update), health check on `/health`, 512M / 0.5 CPU limit, 192M reservation. Swap
  budget: the implicit host allowance; Swarm has no per-task swap knob (docs/adr/2026-10-11-memory-swap-budgeting.md).
- Database `unleash`, role `unleash`, created with `cluster-utils db create-service-db --service feature-flags --db-name
  unleash --db-user unleash --no-push-to-gcp` (no Secret Manager spend). The password lives in `secrets/feature-flags/`
  (git-ignored) and in OpenBao `secret/feature-flags/api`; the service reads `DATABASE_URL_FILE` from the Swarm secret
  named by `FLAGS_DB_URL_SECRET` (versioned, so a rotation ships as a new secret). The local admin password comes from the Swarm secret `feature_flags_admin_password` (exported by a
  shell wrapper, never in the service spec).
- Backups: the database sits on the shared PostgreSQL, whose `postgres-backup` job dumps every connectable database it finds
  (`stacks/main/configs/maintenance/postgres-backup.sh` inventories `pg_database`), so `unleash` is in the nightly dump and
  under the existing `PostgreSQLBackupStatusUnhealthy`, `PostgreSQLBackupMetricsStale` and `PostgreSQLBackupMetricsMissing`
  alerts for `postgres-backup` without a new backup service.
- Routes (websecure, `le-dns`, tailnet only):
  - `flags.${LOCAL_DOMAIN}`: the admin UI behind the shared oauth2-proxy forwardAuth (Keycloak groups of that proxy), then the
    Unleash login (`AUTH_TYPE=open-source`).
  - `flags.${LOCAL_DOMAIN}` with an `Authorization` header on `/api/admin`, `/api/client`, `/api/frontend`: Unleash API
    tokens authenticate; this path keeps working when oauth2-proxy or Keycloak is down (break-glass, SDKs off-cluster).
  - `${FLAGS_FRONTEND_HOSTNAME}/flags/api/frontend`: same-origin frontend evaluation for the application; Traefik strips
    `/flags` and adds the frontend token, so clients carry no token and need no CORS.
  - In-cluster SDKs (MCP server, backend) call `http://main-feature-flags_unleash:4242/api` over the `traefik` overlay.
- Observability: Prometheus job `feature-flags` scrapes `/internal-backstage/prometheus` on both tasks; alerts
  `FeatureFlagServiceDown` (no replica, 3 min, critical) and `FeatureFlagServiceDegraded` (fewer than two, 15 min).
  Container logs reach Loki through the existing Vector pipeline. The application-side dashboard "Errors by flag" and the
  alert on errors under an enabled flag are Grafana-managed in the folder "Feature flags" (dashboard uid
  `feature-flag-errors`, rule `FeatureFlagRaisesErrorRate`: more than 5 `error_flag` lines with the flag on in 15
  minutes for 5 minutes, annotation recommends the kill switch); their definitions are kept in
  `stacks/main/configs/grafana/feature-flags/` and re-applied with the Grafana API after a Grafana rebuild.
- Tokens, created through the admin API after the first start and kept in `secrets/feature-flags/` and OpenBao:
  frontend `japan-route-app-pwa` (production; injected by Traefik), client `japan-route-app-server` (production; Swarm
  secret `feature_flags_client_token` for the MCP server and backend), and a one-year personal access token of the
  local admin for break-glass (expires 2027-11-13; renew it in the admin panel before then).
- Environments: `production` only is used by clients. QA is production; a flag starts targeted to the owner's Keycloak
  subject and widens by segment or sticky percentage.

### What "never fails" means

Evaluation and administration are separate, and evaluation never depends on the service:

1. Clients evaluate from the last snapshot they received (PWA: IndexedDB per person and trip; Android: app storage; server
   SDKs: in-memory ruleset plus the SDK backup file) and fall back to compiled-in safe defaults from the application's flag
   registry. A phone that has never reached the service gets the defaults (new paths dark).
2. The service runs two replicas on two nodes; one replica or node lost leaves the panel and evaluation up.
3. The frontend API answers from the replica's memory while PostgreSQL is down (measured below); the admin panel cannot save
   while the database is down.
4. Break-glass when the panel is unusable: `tools/flags-breakglass` (`flags-breakglass kill <flag>`) switches a flag through
   the admin API with an admin token, and falls back to the Unleash table `feature_environments` when no replica answers but
   the database does; `flags-breakglass export --out <file>` writes the snapshot of every flag.

Limits, stated plainly: if PostgreSQL stays down, a crashed or restarted replica cannot start again, and no flag can change
until it is back; a kill switch issued through the database path takes effect only when the service starts; with every
replica and the database down, a flag can only be forced off by an application release with a changed default. Clients keep
running on their last values in all of these cases. "Never fails" is therefore: the product never stops evaluating, and the
owner always has one documented path to change a flag while the database is up.

## Alternatives

- Pay for Unleash Enterprise or Flagsmith Enterprise for SSO: rejected (no spending; oauth2-proxy covers the need).
- Flipt (OSS OIDC): v2 stores flags in git, not PostgreSQL, and its client-side evaluation ships the namespace ruleset to
  phones, which leaks who is targeted.
- flagd or go-feature-flag: excellent OpenFeature fit, but no admin panel; the owner asked for a panel.
- GrowthBook: needs MongoDB, which the cluster does not run.
- A custom flag table in the application database: rebuilds segments, rollout, audit and UI.
- Header-trust login (oauth2-proxy e-mail mapped into Unleash custom auth): needs custom code in the image and trusts a header
  that any peer on the overlay can forge; rejected for the double gate oauth2-proxy + Unleash login.

## Consequences

- One more two-replica service (about 2 x 200 MB) and one database on the shared PostgreSQL.
- The admin UI asks for the Keycloak login and then the Unleash login. The Unleash event log names the Unleash user;
  create a named user per person instead of sharing `admin`.
- The frontend route trusts the `userId` the client sends; anyone on the tailnet can ask which flags a known subject gets.
  Flags gate presentation and rollout, never data access (row level security does).
- The frontend token is a public-by-design client token kept in the private env and injected by Traefik; it can be rotated in
  the admin panel and `.env` without touching clients.

## Verification

- `tests/test_feature_flags_service.py`: replicas and placement by label, image from the pinned variable, health, limits and
  rollback, secrets as files, Keycloak on the UI route, token-only API route, tailnet domain, Prometheus job, this ADR.
- `tests/prometheus/feature-flags-alerts.test.yml`: both alerts with promtool.
- `tools/flags-breakglass/tests`: admin API path with read-back, database fallback, explicit failures.
- Live failure tests and results: section "Failure tests 2026-11-13" below.

## Failure tests 2026-11-13

Run on the manager against the live stack (UTC). "frontend" is the same-origin frontend route asked for the owner's
subject (5 flags on for the owner); "admin API" is a token call to `/api/admin/projects/default/features` through the
token route (the panel's backend); the browser route answered its oauth2-proxy redirect (302) throughout.

| Test | What was done | Frontend evaluation | Admin API | Recovery |
| --- | --- | --- | --- | --- |
| Kill one replica | `docker kill` of the manager task, 09:54:50 | 200 with 5 flags every 6 s | not measured in this run | 2/2 after 31 s |
| Database cut | role `unleash` set NOLOGIN and its 6 backends terminated, 09:55:38 to 09:57:57 | 200 with 5 flags for 2 min 20 s | | the replicas crashed in turn (exit 1) and restarted while the other served; 2/2 21 s after LOGIN was restored |
| Whole service down | scale to 0, 09:59:57 and 10:08:37 | 502 (clients use their snapshot or defaults) | 502 | scale 2: 200 again after about 40 s |
| Break-glass, API path | `flags-breakglass kill flags.selftest` then `enable`, 10:08:26 | 4 flags, then 5 | verified read-back | immediate |
| Break-glass, database path | same `kill` with every replica down, 10:09:13 | after the restart 4 flags (the kill took effect) | | `enable` restored 5 |

Grafana path: a synthetic `jra.error/1` `error_flag` line (code `FLAGS_SELFTEST`) emitted at 10:10:14 was counted by the
"Errors per flag and variant" query in Loki.

Not tested live: the browser login through Keycloak to the Unleash UI (needs the owner's credential), PostgreSQL itself
stopped (shared by every service; the role cut reproduces the same loss for Unleash only), a node lost.

Incident during the tests: the first database-path run printed a fragment of the database password in a psycopg DSN
parse error inside the agent transcript. The password was rotated at 10:02 (new secret `feature_flags_db_url_v2`,
OpenBao updated, old secret removed) and the CLI now reports database failures by error class only, with a test.

## Rollback

- Service update: `docker service rollback main-feature-flags_unleash` (automatic on a failed update).
- Remove the service: `docker stack rm main-feature-flags`; the database, the secrets and OpenBao custody stay, and clients keep
  evaluating from their caches and defaults. Redeploy with `uv run cluster-utils deploy stack main-feature-flags`.
- Prometheus: revert the `feature-flags` job and alert group, bump `CONFIG_VERSION`, `uv run cluster-utils deploy service prometheus`.
