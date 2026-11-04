# ADR: MLflow authentication through the mlflow-oidc-auth plugin

Date: 2026-10-13. Status: accepted and deployed (`ml-registry_mlflow`, image `mlflow-oidc` 0.1.1).
Supersedes the earlier edge design (oauth2-proxy forwardAuth in front of MLflow 2.18.0, described in the
previous `stacks/ml/README.md`). Origin: item 4 of the Authelia-to-Keycloak migration plan.

## Context

- MLflow ran as `ghcr.io/mlflow/mlflow:v2.18.0` with `pip install psycopg2-binary` at every container start, a
  PostgreSQL backend and a local-volume artifact root. Authentication was the shared oauth2-proxy
  (`allowed_groups = [admin, mlflow-admin]`, `skip_jwt_bearer_tokens`), so MLflow itself saw no user identity.
- The server held no data worth keeping when this was decided: one `Default` experiment, zero runs, models or
  parameters, an 8 MB database, an empty artifact volume (checked 2026-10-13).
- Clients: browsers (Keycloak SSO) and automation (gpu-idle-lab, artifact-sync) using Keycloak client-credentials
  tokens from the confidential client `mlflow-api`, sent as `Authorization: Bearer`.
- The repository is public, so the private registry path stays in the untracked `.env` (`MLFLOW_OIDC_IMAGE`).

## Decision

Adopt [`mlflow-oidc-auth`](https://github.com/mlflow-oidc/mlflow-oidc-auth) 9.0.4 (Apache-2.0) and serve MLflow with
`mlflow server --app-name oidc-auth`. This requires MLflow 3.x: every plugin release since 6.0 (January 2026) needs
`mlflow>=3.8` and 9.0.4 needs `>=3.16,<4`; releases 5.x supported MLflow 2.21+ but not the deployed 2.18. The image
`mlflow-oidc` pins MLflow 3.17.0, the plugin, psycopg2-binary and SQLAlchemy 2.0.x from a hash-locked
requirements file on a digest-pinned `python:3.12-slim`, and runs as UID 65532.

Configuration (see `stacks/ml/registry.yml`): Keycloak discovery URL and confidential client `mlflow-oidc` (PKCE S256,
redirect `/callback`); `OIDC_GROUP_NAME=admin,mlflow-admin`, `OIDC_ADMIN_GROUP_NAME=mlflow-admin`; bearer tokens validated
for issuer and audience `mlflow-oidc` (an audience mapper on `mlflow-api` adds it), accounts created on first bearer use
and made administrators from the `groups` claim (`OIDC_TRUST_BEARER_GROUP_CLAIMS`, acceptable because Keycloak owns the
claim); plugin tables in the MLflow PostgreSQL database with `OIDC_ALEMBIC_VERSION_TABLE=alembic_version_oidc`;
credentials as Swarm secret files read by the image entrypoint (`*_FILE`); `MLFLOW_DISABLE_TELEMETRY=true`;
`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` and `--workers 1`.

The image is overridable through `MLFLOW_OIDC_IMAGE` in the operator `.env`, the same pattern as
`EPHEMERAL_REBALANCE_IMAGE`; `registry.yml` has no fallback.

## Alternatives

- **Keep oauth2-proxy in front of MLflow 2.18.** Works, needs no migration and had a verified bearer path. Rejected
  because MLflow cannot attribute runs to users, offers no per-experiment permissions, depends on a global proxy
  allow-list shared with unrelated apps, and keeps the start-time `pip install` and an old MLflow that was being
  OOM-killed (SIGKILL workers in the previous service log). The decisive factors were the empty database (no migration
  cost) and the stated intent to retire reliance on the shared proxy.
- **MLflow 3.x with its built-in basic auth.** No Keycloak, no SSO. Rejected.
- **Other plugins.** None with comparable scope was found; vetting of the chosen plugin is in the Agent Memory vault
  (entity `mlflow-oidc-auth`): 131 stars, two maintainers writing about 90 percent of the commits, 141 releases and
  five major versions in about 16 months, last release 2026-10-06, 4 open issues, no `eval`/`exec`/telemetry in the
  wheel, extensive bundled tests. Adoptable with the caveat of a small, fast-moving project.

## Consequences

- Plugin majors raise the minimum MLflow version; upgrade both together, never the plugin alone, and canary a new
  image on a second host name with a throwaway SQLite database before changing `MLFLOW_OIDC_IMAGE`.
- Non-admin bearer users get 403 on the `Default` experiment (it has no owner); service accounts in `mlflow-admin`
  are administrators and are unaffected.
- SQLAlchemy 2.1 maps `postgresql://` to psycopg v3, which is not in the image; the lock pins 2.0.x (image 0.1.1).
- MLflow memory settled near 0.4 GiB (limit 2 GiB) against four workers plus a job-runner pool that exceeded 1.4 GiB.
- Cold pulls of the private image on a node without registry credentials fail; the image is pre-pulled on the leader
  (placement is `node.labels.swarm.leader == true`, which also keeps the local artifact volume on one node).

## Rollback

1. Database backup before cutover: `mlflow-precutover-<timestamp>.dump` in the `mlflow-backups` directory of the operator account on the manager (`pg_dump -Fc
   --no-owner`, mode 0600, with `.sha256`), 19 tables.
2. Service: restore the pre-change `registry.yml` copy (kept in the private deployment records) over `stacks/ml/registry.yml`, then
   `pg_restore --clean --if-exists --no-owner` of the dump into the `mlflow` database, then
   `uv run cluster-utils deploy service mlflow --compose-file stacks/ml/registry.yml --stack-name ml-registry`.
   `docker service rollback ml-registry_mlflow` returns only the service spec, not the migrated schema.
3. Keycloak additions (`mlflow-oidc` client, audience mapper `aud-mlflow-oidc` on `mlflow-api`) are additive and
   harmless to leave.

## Verification (2026-10-13)

- Restored the production dump into a throwaway PostgreSQL 17: `mlflow db upgrade` took the schema from
  `0584bdc529eb` to `dc11669786a5`, the OIDC server started against it with both Alembic tables, and restoring the
  dump over the migrated copy brought back `0584bdc529eb` with the 2.18.0 server answering `experiments/search`.
  (This test also caught the SQLAlchemy 2.1 incompatibility, fixed in 0.1.1.)
- Throwaway instance on its own host name and SQLite: login redirect with PKCE, bearer token from `mlflow-api` accepted,
  invalid token 401, administrator provisioning from the groups claim.
- Live: `/health` 200, anonymous `/` and API 401, MLflow Python client logging a run with a client-credentials token,
  browser login through Keycloak showing the MLflow 3.17.0 UI and listing experiments, and a user outside the allowed
  groups receiving "User is not allowed to login" until added to `mlflow-admin`.

Not verified: logout, token expiry mid-session, personal access tokens, per-experiment permission grants.
