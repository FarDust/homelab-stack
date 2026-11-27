# Changelog

## Unreleased

- Lower the `llms-governance_open-webui` memory limit from 8G to 3G and add a 768M reservation (7-day peak 644 MB resident, 1,245 MB with swap). No swap setting is added; the benefit is small because the swapped pages are cold. See `docs/adr/open_webui_memory_limit_adr.md`.
- Fix: `vault-sync` stops its cycle at the first HTTP 401/402/403/429 from the model backend instead of repeating the failing call for every vault file. With `DRY_RUN=true` the manifest never advances, so every file was re-extracted each cycle: about 8,000 `gpt-5-mini` calls a day answered 429 "no credits remaining" through LiteLLM since 2026-11-10. Extraction resumes by itself when credits return.
- Raise the default of `LITELLM_COMMIT_GUARD_FLOOR_GIB` from 6 to 11 GiB: a cold Ollama load adds about 10 GB of commit, so a 6 GiB floor admitted loads that could exhaust the host (minimum headroom 1.1 GiB observed on 2026-11-27). Set the variable to 6 to roll back.
- Fix: the LiteLLM commit-headroom guard no longer uses `from __future__ import annotations`; LiteLLM loads callbacks without a `sys.modules` entry and the dataclass crashed proxy startup. The test now loads the hook the same way.
- Add the LiteLLM commit-headroom guard (`stacks/llms/configs/litellm/commit_headroom_guard.py`), dark behind the per-key flag `LITELLM_COMMIT_GUARD_KEY_ALIASES`: a cold load on the gabriel-pc Ollama gets HTTP 503 with `Retry-After` and an explicit reason when Windows free virtual memory is under `LITELLM_COMMIT_GUARD_FLOOR_GIB` (default 6); missing, stale or malformed signal fails closed. `tools/memory-guard` 0.4.0 adds `publish-headroom` (flag `MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED`), which writes the headroom into the gabriel-pc-wsl node-exporter textfile collector every minute without starting WSL. See `docs/adr/litellm_commit_headroom_guard_adr.md`.
- Set `OLLAMA_KEEP_ALIVE=45s` on `llms-governance_ollama` (default was 5 minutes) so the GPU model unloads sooner after a chat burst and the WSL VM gives its commit back; `OLLAMA_CONTEXT_LENGTH=128000` is unchanged (`docs/adr/ollama_keep_alive_45s_adr.md`).
- `tools/node-retention` 0.7.0: sweep dead pytest scratch runs (`run-<pid>-<random>`) on fixed-size scratch volumes such as frost-fang's `/ps`: a dead pid goes after 2 h idle, and above a 4 GiB cap the oldest dead ones after 15 min idle; live pids, symlinks and other names are never touched. See `docs/adr/node_disk_retention_adr.md`.
- `tools/memory-guard` 0.1.1: a failed alert attempt counts toward the rate limit; the run still exits 1.
- Add `tools/memory-guard` 0.1.0: read-only Windows memory-pressure watchdog (commit limit, free RAM, non-paged pool, top 10 processes by private bytes) that alerts through agent-bridge after two low samples, one alert per condition per 30 minutes, with a recovery message. Task Scheduler launcher every 5 minutes at BelowNormal. See `docs/adr/memory_guard_adr.md`.
- Add `tools/open-prs-feed` 0.1.0: writes the open pull request list (`open-prs.json`) that node-retention 0.6.0 reads to release job directories of merged or closed PRs, plus a detail file with head SHA, branch and update time. Fails closed and keeps the last good file on any source failure, malformed row, truncated page or empty answer. See `docs/adr/open_prs_feed_adr.md`.
- Fix: add reviewed host rsyslog source using `maxsize 5G` so the daily and weekly schedules remain effective. Node-retention 0.3.1 adds native debug regression checks using its existing Python 3.13 pin. Activation remains separate and requires preservation of diagnostic history; see `docs/adr/rsyslog_retention_schedule_adr.md`.

## 0.3.0

- Add to `tools/node-retention` 0.3.0: a `protected_image_refs` setting (reference to expected image id, JSON in `NODE_RETENTION_PROTECTED_IMAGE_REFS`, empty by default) that guards a CI helper image that jobs run with `--pull=never`. Before any image prune, `plan` and `apply` check every protected reference; a missing reference or another id refuses the prune, makes `plan` and `apply` exit 1 with the reference, expected id and observed id, and marks the run failed in the manifest, ledger row and metrics. A new `verify-images` command applies the same rule for scripts that prune on their own. The Docker adapter refuses any prune subcommand with `-a` in any spelling, `--all` or `--volumes`. Expected ids are validated as `sha256:<64 hex>` and an image lookup that fails, times out, finds no docker binary or answers empty aborts the run and leaves a failed ledger row. See `docs/adr/node_disk_retention_adr.md`.

## 0.2.0

- Add `main/feature-flags`: the cluster feature-flag service (Unleash OSS 8.3.1 pinned by digest, two replicas on two stable nodes, database through `cluster-utils db create-service-db`, covered by the existing `postgres-backup` job), its admin panel behind Keycloak through the shared oauth2-proxy, a token-only API route for SDKs and break-glass, and a same-origin frontend route for applications. See `docs/adr/feature_flags_service_adr.md`.
- Add: Prometheus job `feature-flags` with `FeatureFlagServiceDown` and `FeatureFlagServiceDegraded` (promtool tests), the Grafana "Errors by feature flag" dashboard and `FeatureFlagRaisesErrorRate` alert definitions, and the `tools/flags-breakglass` uv package (admin API with read-back, database fallback when the service is down).
- Add (independent review): `flags-breakglass` 0.2.0 has `--dry-run` on `kill` and `enable`, and treats a rejected token (HTTP 401/403) as an explicit failure instead of falling back to the database behind a running service. The ADR states the AGPL-3.0 private-use position and records the review's live checks (replica kill, stop-first rolling update, per-user frontend evaluation, log scan) and open findings.

## 0.1.9

- Add `tools/node-retention` 0.2.0, the standing disk retention policy for the build worker: plan (dry run), apply and guard commands, manifest before every deletion, ledger rows `who=retention`, textfile metrics and two systemd user timers. Deletion is fail-closed: an unreadable job ledger stops the run, paths of running ledger jobs, trees with a mount point or a Unix socket, symlinked ancestors and roots under system or Docker trees are never deleted, and safety is re-checked just before each delete. See `docs/adr/node_disk_retention_adr.md`.
- Prometheus: `NodeRootFreeBelowRetentionFloor`, `NodeRetentionStale`, `NodeRetentionRunFailed` and `MinecraftServerMemoryNear16G` alerts with rule tests. See `docs/adr/minecraft_memory_budget_adr.md`.
- CI: the node-retention test suite runs in the pre-commit workflow.

## 0.1.8

- Fix `main/traefik`: the `HOMELAB_PRIVATE_DIR` required-variable messages contained hyphens, which `docker stack deploy` reads as the default operator, so the Prometheus ingress probe targets and five Grafana dashboards resolved to a wrong path and the services could not be redeployed. Messages are hyphen-free and guarded by a test. See `docs/adr/swarm_interpolation_required_message_adr.md`.

## 0.1.7

- Docs: the HDD-backed node record now covers memory. Job scratch moved to tmpfs became swap-out; adds the admission signal, the per-job footprint, the node budget and the runtime zswap change. No stack configuration changes.

## 0.1.6

- ClickHouse: pin the exact running release by digest and remove the self-telemetry tables (`trace_log`, `text_log`, `metric_log`, `asynchronous_metric_log`, `part_log` and related) that wrote to the data disk around the clock; `query_log` and `crash_log` stay. Existing tables are kept.
- Prometheus: `HostIoPressureSustained` and `HostDiskSaturated` alerts with rule tests.
- Docs: troubleshooting note for throwaway test databases. See `docs/adr/hdd_node_io_budget_adr.md`.

## 0.1.5

- Static journey nginx: compress text assets with gzip and serve a static `/reset` recovery page with `Cache-Control: no-store`. The versioned config name changes with `JOURNEY_VERSION`, so the next rollout of the stack picks it up.

## 0.1.4

- Stagger the start of the GPU and AI services on the ephemeral GPU node after a VM start: an uptime-slot startup gate in the entrypoint of whisper, ollama, jellyfin, jellyseerr, sonarr, radarr, bazarr, qbittorrent, jupyter-tensorflow and comfy-gpu, ordered restart delays, memory reservations and a longer whisper start period. `vllm-gemma4` stays at zero replicas. See `docs/adr/gpu_node_staggered_start_adr.md`.

## 0.1.3

- Pin Traefik to the previously deployed immutable digest so a routing-only service update cannot silently upgrade the proxy through the floating `latest` tag.

## 0.1.2

- Resolve the exact OpenBao and Keycloak TLS hostnames to Traefik's existing `trust-internal` endpoint for Trust Agent consumers. This preserves TLS/SNI and network segmentation while avoiding an unreachable container-to-local-Tailscale hairpin.

## 0.1.1

- Refresh vulnerable Python dependency locks within the existing declared constraints, including AnyIO 4.14.2, LiteLLM 1.88.6, aiohttp 3.14.3, urllib3 2.8.0, Mako 1.4.2, multidict 6.9.1, and patched HTTP, parsing, and serialization dependencies.
- Preserve the existing cryptography 46, virtualenv 20, langsmith 0.6, and langgraph-sdk 0.3 compatibility lines. Advisories requiring incompatible upgrades remain open for a separately validated migration.
- Keep the editable cluster-utils source declaration unchanged. No stack configuration, deployment, service state, or credentials are changed.
