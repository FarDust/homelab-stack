# Keycloak runs from a pre-built image with `start --optimized`

## Context

`main-identity_keycloak` ran the stock `quay.io/keycloak/keycloak:26.4.7` image with `start`. Without `--optimized`, every container start re-runs the Quarkus build step ("Updating the configuration and installing your custom providers"). Measured on 2026-10-13: container start 06:56:03 UTC, server ready 06:57:41 UTC, so about 98 s of boot plus the stop of the old task, roughly two minutes of SSO outage (oauth2-proxy, Grafana, MLflow and every OIDC client) per restart. On 2026-10-12 the service never became ready between Swarm heartbeat flaps. [keycloak_pinned_placement_adr.md](keycloak_pinned_placement_adr.md) removed the rebalancer as a cause; this decision shortens the outage whatever the cause.

## Decision

Build our own image from `stacks/main/keycloak-optimized/` (`Dockerfile`, `VERSION`, `CHANGELOG.md`, Semantic Versioning, first release 0.1.0) and run it with `start --optimized`.

- Base: the same Keycloak as deployed, `26.4.7`, pinned by digest (`sha256:9409c59b...`, taken from the running task and checked against `kc.sh --version` in the live container).
- Build-time options, derived from the live run configuration (`kc.sh show-config` in the running container): `db=postgres` (was `KC_DB`), `health-enabled=true`, `metrics-enabled=true` and `vault=file` (the live service already had `KC_VAULT=file` for Docker-secret references in realm settings). Health and metrics were not enabled before; they are added because the readiness probe (`/health/ready` on management port 9000, used by the image `HEALTHCHECK`) and a future Prometheus scrape need them, and the management port is not routed by Traefik. No features (`KC_FEATURES` unset) and no custom providers (`/opt/keycloak/providers` empty), so none are built in.
- Runtime options stay in the compose file: `--http-enabled`, `--proxy-headers=xforwarded`, `--hostname`, the database URL and credentials, vault directory.
- The image creates an empty `/run/secrets`: with `vault=file` Keycloak aborts when the directory is missing, and the Swarm secret mount replaces it at runtime. This was found by the throwaway test.
- Compose references `${KEYCLOAK_IMAGE?err}`, set in the untracked operator `.env` to the digest-qualified Artifact Registry reference (same pattern as `MLFLOW_OIDC_IMAGE`, `EPHEMERAL_REBALANCE_IMAGE`). No fallback value.
- Build and publish: on frost-fang under `flock /tmp/ci-build.lock` with `nice`/`ionice` after checking `/proc/pressure/io`; push to `cluster-internal-images` with a short-lived `gcloud` access token on stdin into a temporary 0700 `DOCKER_CONFIG`; the image is also present on frost-fang, the node Keycloak is pinned to, so the update uses `--no-resolve-image`. Never on fardustdev.
- Upgrades: bump `KEYCLOAK_BASE` and the image MINOR version together, validate on a throwaway instance with a restored dump, then roll out. The build options are persisted in the image, so a Keycloak upgrade needs a new image by design.

## Alternatives

- Keep `start` and accept ~100 s restarts: rejected, identity is a dependency of every protected route.
- `--optimized` on the stock image: the stock image has no persisted build, so there is nothing to optimize.
- `cache=local` (build option): would also skip JGroups join retries after an ungraceful stop (a stale `jgroups_ping` row costs about 20 s) but changes clustering behavior; not needed for one replica and left as a separate decision.
- `order: start-first` updates: rejected for now, two Keycloaks would share the database and the JGroups table during the overlap.
- Mount a prebuilt Quarkus build as a volume: rejected, an image is the supported mechanism.

## Consequences

- Restart cost drops from about 98 s of boot to 6 to 15 s. A Keycloak version change now requires building and publishing a new image.
- The image must exist on frost-fang or be pullable there (registry auth is not forwarded by `cluster-utils deploy`; pre-pull as for the other private images).
- `vault=file` and health/metrics are fixed into the image; changing them is an image release.
- Rollback: `docker service update --no-resolve-image --image quay.io/keycloak/keycloak:26.4.7@sha256:9409c59bdfb65dbffa20b11e6f18b8abb9281d480c7ca402f51ed3d5977e6007 --args "start --http-enabled=true --proxy-headers=xforwarded --hostname=https://idp.${LOCAL_DOMAIN}" main-identity_keycloak`, then revert the compose hunk and `.env`. A `pg_dump` taken before the change (custom format, 2.4 MB, 5 realms, 58 clients, 17 users) is on frost-fang in `~/keycloak-optimized-rollback/` with its checksum. No schema change was made: the same Keycloak version runs against the same database.

## Verification (2026-10-13)

Throwaway instance (image 0.1.0, restored dump, isolated Docker network, port bound to 127.0.0.1 and reached through an SSH tunnel, hostname `http://localhost:18943`):

- Ready in about 8 s from container start (`started in` 5.8 to 7.1 s) with a clean `jgroups_ping`; 33 s the first time because the restored dump carried the stale JGroups entry of the live node (about 20 s of join retries against an unreachable address).
- No "Updating the configuration" line in the log: the optimized start path was used.
- OIDC discovery for realm `sigilcore` 200; client-credentials tokens 200 for `mlflow-api` (sigilcore; audience `oauth2-proxy`, `mlflow-oidc`; group `mlflow-admin`) and `loki-api` (pomerium).
- Admin API (temporary admin service client created in the copy only): five realms listed, client counts equal to the dump; `grafana` (redirect `https://grafana.${DOMAIN_NAME}/login/generic_oauth`, `groups-claim` mapper) and `oauth2-proxy` (redirect `https://oauth2.${LOCAL_DOMAIN}/oauth2/callback`, `groups-claim` mapper) intact.
- `kc.sh export --users realm_file` against the copy exported all five realms in 53 s; this is the realm export approach (files hold secrets, so delete them after use).
- The Brave debug browser reached the "Sign in to sigilcore" form for the account console; no credential was entered.
- The throwaway containers, network, secrets and export files were removed.

Live cutover (one restart, announced): the update ran with `docker service update` using exactly the image and `--optimized` change, because the working tree compose file also carries another session's uncommitted vault and SMTP hunks (already live) that this change does not touch. After it: discovery 200, oauth2-proxy 1/1, client-credentials token 200, Grafana `/login/generic_oauth` 302 to the `sigilcore` authorize endpoint with `client_id=grafana`, MLflow `/login` 302 to Keycloak with `client_id=mlflow-oidc`, oauth2-proxy `/oauth2/start` 302 to Keycloak with `client_id=oauth2-proxy`.

Measured restarts (probe of the discovery URL through Traefik every 0.25 to 0.5 s; outage from first to last non-200):

| Change | Keycloak boot | Outage |
| --- | --- | --- |
| Before (stock image, `start`), forced update 2026-10-13 06:55 UTC | 98 s | about 2 minutes |
| Cutover to 0.1.0 | 6.1 s | 30 s |
| Second forced update on 0.1.0 | 11.7 s | 29.8 s |

The remaining 30 s are the graceful stop of the old task (about 10 s), the JVM start, the first `HEALTHCHECK` probe and Traefik picking up the new task. Tuning candidates: `--start-interval` on the health check, a shorter stop grace period, `cache=local`.
