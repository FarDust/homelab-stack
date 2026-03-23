# LLM stacks (optional)

Compose under this directory is **optional**. It adds AI/LLM-related services that assume you already run the **core platform** (edge, shared databases, and observability from your `main-*` stacks). Expect significant **RAM** and optionally **GPU** use.

## Scope (what belongs in `stacks/llms/`)

- **Belongs here:** **LLM-facing applications and glue**: agents, governance, MCP servers, monitoring tailored to LLM workloads, and similar (see compose files below). Focus is **inference, agents, and LLM ops**, not generic cluster-wide metrics collectors.
- **Add a compose file here** when the service exists primarily to **serve, steer, or observe language models** in this environment.

## Compose files

| File | Role (high level) |
|------|-------------------|
| [`agents.yml`](agents.yml) | Agent-related services |
| [`evaluation.yml`](evaluation.yml) | Prompt evaluation and red-team testing (promptfoo) |
| [`governance.yml`](governance.yml) | Governance / policy-related tooling |
| [`mcp.yml`](mcp.yml) | MCP-related services |
| [`monitoring.yml`](monitoring.yml) | Monitoring for LLM workloads |

Configs live in [`configs/`](configs/). Refer to each upstream project for model lists, env vars, and sizing.

## Deploy

Use the same Swarm naming as elsewhere: e.g. `stacks/llms/mcp.yml` → stack name **`llms-mcp`**. Deploy with `uv run cluster-utils deploy` after `source .env` (see repository [AGENTS.md](../../AGENTS.md)).
