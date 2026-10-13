# ML stack

Compose for **ML workflow orchestration** on the Swarm cluster: pipelines and metadata services, not interactive LLM chat or agent frontends.

## Scope (what belongs in `stacks/ml/`)

- **Belongs here:** **Training and workflow orchestration** plumbing (e.g. Metaflow metadata and UI) that supports ML **pipelines** and experiment tracking, not interactive chat frontends.
- **Add a compose file here** when the workload is **orchestration, metadata, or batch ML flow** outside the core platform compose files. Metaflow metadata still needs a database; wire that in env (often Postgres from the core storage stack).

## Compose files

| File | Role (high level) |
|------|-------------------|
| [`orchestration.yml`](orchestration.yml) | Metaflow metadata service and UI (`metaflow.*`, `metaflow-ui.*` on `${LOCAL_DOMAIN}`) |
| [`registry.yml`](registry.yml) | MLflow (`mlflow.${LOCAL_DOMAIN}`) — experiments and model registry |

Requires a PostgreSQL database for Metaflow metadata (see env vars `MF_METADATA_*` in the compose file). MLflow needs its own Postgres database, its image variable `MLFLOW_OIDC_IMAGE` and the `MLFLOW_*` variables (see `.env.example`).

## Authentication (MLflow OIDC plugin)

MLflow authenticates natively through the [`mlflow-oidc-auth`](https://github.com/mlflow-oidc/mlflow-oidc-auth) plugin against Keycloak (realm `$KEYCLOAK_SIGILCORE_REALM`). The route no longer uses the shared oauth2-proxy forwardAuth. Decision, alternatives and rollback: [docs/adr/mlflow_oidc_auth_adr.md](../../docs/adr/mlflow_oidc_auth_adr.md).

- **Routing:** one Traefik router in [`registry.yml`](registry.yml) with no forwardAuth middleware. `GET /health` is unauthenticated inside the application, for Traefik load-balancer checks.
- **Browser:** confidential client **`mlflow-oidc`** (standard flow, PKCE S256, redirect `https://mlflow.${LOCAL_DOMAIN}/callback`, web origin `https://mlflow.${LOCAL_DOMAIN}`). Unauthenticated browsers are redirected to Keycloak (`AUTOMATIC_LOGIN_REDIRECT`). Only members of the Keycloak groups **`admin`** or **`mlflow-admin`** (claim `groups`) may log in; **`mlflow-admin`** members are MLflow administrators. Any other user sees "User is not allowed to login".
- **Automation / API:** send a Keycloak access token as `Authorization: Bearer <token>` (the MLflow Python client does this with `MLFLOW_TRACKING_TOKEN`). The confidential client **`mlflow-api`** (client credentials) carries an audience mapper that adds **`mlflow-oidc`** to `aud` and is in group `mlflow-admin`, so its token is accepted and its account is created on first use as an administrator (`OIDC_PROVISION_ON_BEARER_AUTH`, `OIDC_TRUST_BEARER_GROUP_CLAIMS`). Unset `MLFLOW_TRACKING_USERNAME`/`MLFLOW_TRACKING_PASSWORD` in jobs that use a bearer token, because basic auth takes precedence.
- **Provision the clients** with `uv run cluster-utils keycloak upsert-oidc-client`, `upsert-group-mapper` and `upsert-audience-mapper`; the client secret is stored in `secrets/mlflow/oidc_client_secret`. The session signing key is `secrets/mlflow/session_key` and the PostgreSQL URI is `secrets/mlflow/backend_store_uri`; Swarm mounts them as files (`*_FILE` variables handled by the image entrypoint).
- **Plugin tables** (users, permissions, sessions) live in the MLflow PostgreSQL database; their Alembic version table is `alembic_version_oidc` so it does not collide with MLflow's `alembic_version`.

## Image

[`registry.yml`](registry.yml) runs `${MLFLOW_OIDC_IMAGE}`, a digest-qualified image built from [`mlflow-oidc/`](mlflow-oidc/) (MLflow, the plugin and psycopg2 installed from a hash-locked requirements file; see its [CHANGELOG](mlflow-oidc/CHANGELOG.md)). Set it in the untracked operator `.env` (`.env.example` shows the shape). Build on frost-fang under `flock /tmp/ci-build.lock` once `/proc/pressure/io` is calm, push to the private Artifact Registry repository `cluster-internal-images`, pin by digest, and pre-pull on the nodes that may run MLflow, as for the other private images.

## Verification

**Browser E2E is mandatory** for auth/UI: follow the **Chrome DevTools** steps in [AGENTS.md](../../AGENTS.md); `curl` alone is not enough. Supplementary checks from a Swarm manager (SNI to the public hostname via the Traefik VIP):

```bash
H=mlflow.${LOCAL_DOMAIN}
C="docker run --rm --network traefik-public curlimages/curl:8.10.1 -skS --connect-to $H:443:main-traefik_traefik:443"
$C -o /dev/null -w "%{http_code}\n" https://$H/health   # 200, no auth
$C -o /dev/null -w "%{http_code}\n" https://$H/         # 401 without a session (browsers are redirected to Keycloak)
```

Bearer API with the Python client:

```bash
# After: set -a; source .env; set +a  (MLFLOW_API_CLIENT_ID / MLFLOW_API_CLIENT_SECRET set)
export MLFLOW_TRACKING_URI=https://mlflow.${LOCAL_DOMAIN}
export MLFLOW_TRACKING_TOKEN=$(curl -sS -X POST "https://idp.${LOCAL_DOMAIN}/realms/${KEYCLOAK_SIGILCORE_REALM}/protocol/openid-connect/token" \
  -d grant_type=client_credentials -d client_id="${MLFLOW_API_CLIENT_ID}" -d client_secret="${MLFLOW_API_CLIENT_SECRET}" | jq -r .access_token)
uv run --no-project --with mlflow-skinny==3.17.0 python -c "import mlflow; print(mlflow.search_experiments())"
```

Tokens are short-lived; refresh `MLFLOW_TRACKING_TOKEN` for long jobs.

## Deploy

Swarm names: **`ml-orchestration`** for `stacks/ml/orchestration.yml`, **`ml-registry`** for `stacks/ml/registry.yml`.

From the repo root after `set -a; source .env; set +a`:

```bash
uv run cluster-utils deploy stack ml-orchestration
uv run cluster-utils deploy service mlflow --compose-file stacks/ml/registry.yml --stack-name ml-registry
```

Back up the MLflow database before any MLflow version change (`pg_dump -Fc`); a restore over the migrated database returns MLflow 2.x to a working state (verified on a copy, see the ADR). See [AGENTS.md](../../AGENTS.md) for `deploy service` details.
