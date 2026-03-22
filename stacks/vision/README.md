# Vision stack

Compose for **image generation** workloads (GPU-backed) on the Swarm cluster.

## Scope (what belongs in `stacks/vision/`)

- **Belongs here:** **Image and video-gen** workloads that need **GPU** placement and heavy model storage (e.g. ComfyUI in `generation.yml`).
- **Add a compose file here** for new **generative vision** services that share this operational profile (GPU labels, large model volumes).

## Compose files

| File | Role (high level) |
|------|-------------------|
| [`generation.yml`](generation.yml) | ComfyUI behind Traefik at `comfy.${LOCAL_DOMAIN}` |

Uses node labels `gpu` / `gpu.class` for placement. Model and output paths use **rclone** volumes (see the compose file).

## Config

- [`configs/stable-diffusion/extra_model_paths.yaml`](configs/stable-diffusion/extra_model_paths.yaml) for extra model path hints where applicable.

## Deploy

Swarm name: **`vision-generation`** for `stacks/vision/generation.yml`. Deploy with `uv run cluster-utils deploy` after `source .env` (see [AGENTS.md](../../AGENTS.md)).
