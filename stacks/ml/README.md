# ML stack

Compose for **ML workflow orchestration** on the Swarm cluster: pipelines and metadata services, not interactive LLM chat or agent frontends.

## Scope (what belongs in `stacks/ml/`)

- **Belongs here:** **Training and workflow orchestration** plumbing (e.g. Metaflow metadata and UI) that supports ML **pipelines** and experiment tracking, not interactive chat frontends.
- **Add a compose file here** when the workload is **orchestration, metadata, or batch ML flow** outside the core platform compose files. Metaflow metadata still needs a database; wire that in env (often Postgres from the core storage stack).

## Compose files

| File | Role (high level) |
|------|-------------------|
| [`orchestration.yml`](orchestration.yml) | Metaflow metadata service and UI (`metaflow.*`, `metaflow-ui.*` on `${LOCAL_DOMAIN}`) |

Requires a PostgreSQL database for Metaflow metadata (see env vars `MF_METADATA_*` in the compose file).

## Deploy

Swarm name: **`ml-orchestration`** for `stacks/ml/orchestration.yml`. Deploy with `uv run cluster-utils deploy` after `source .env` (see [AGENTS.md](../../AGENTS.md)).
