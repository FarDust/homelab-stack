# Apps stack (Swarm)

Homelab-owned compose for application-style services.

## Scope (what belongs in `stacks/apps/`)

- **Belongs here:** **First-party application stacks** you treat as products: packaged app bundles (e.g. Supabase) and **`web.yml`** for site or app frontends outside the core platform compose files.
- **Add a compose file here** when you are deploying an **application** or **multi-service app bundle** as its own Swarm stack, separate from edge routing and shared databases in **`main-*`**.

- **[supabase.yml](supabase.yml)**: Supabase on Docker Swarm for this environment.
- **[web.yml](web.yml)**: Web frontends or related apps as defined in compose.

Upstream Supabase **reference** material (docker templates, etc.) is vendored as a git submodule at [`../main/configs/supabase`](../main/configs/supabase) (`supabase/supabase` upstream). **Do not commit edits inside that submodule path** here; bump the submodule pointer when you intentionally upgrade vendor content.

## Deploy

Swarm stack names follow `apps-<filename>`: `stacks/apps/supabase.yml` → **`apps-supabase`**, `stacks/apps/web.yml` → **`apps-web`**. From the repo root: `set -a; source .env; set +a` then `uv run cluster-utils deploy --help` (see [AGENTS.md](../../AGENTS.md)).
