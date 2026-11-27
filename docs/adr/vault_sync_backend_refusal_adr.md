# Vault-sync stops its cycle when the model backend refuses requests

Status: accepted 2026-11-27.

## Context

`main-maintenance_vault-sync` (`stacks/main/configs/maintenance/vault_sync.py`) extracts entities from the cluster vault with `gpt-5-mini` through LiteLLM every 1800 s. It runs with `DRY_RUN=true`, so the manifest never advances and every cycle sends every vault file again. Since 2026-11-10 15:16Z the OpenAI account answers HTTP 429 "You have no credits remaining": each file failed, was logged and skipped, and the next file was tried at once. LiteLLM spend logs showed about 8,000 failed `gpt-5-mini` calls a day from user agent `python-httpx` with no key alias (10.0.1.3 is the Traefik network endpoint, which hid the client address).

## Decision

`extract_entities` raises `ExtractionBackendRefused` for HTTP 401, 402, 403 and 429. `sync_once` logs one line and returns, so the cycle ends and the next attempt happens after `SYNC_INTERVAL_SECONDS`. Every other error keeps the per-file skip. The integration stays enabled; it resumes by itself when credits return.

## Alternatives

- Scale the service to 0: removes the output of a dry run nobody reads, but also removes the sync when credits return, and needs a manual restore.
- Route to a local or Vertex model: spends money or loads a 10 GB Ollama model, which this host cannot afford (see `litellm_commit_headroom_guard_adr.md`).
- Backoff per file: still one failing call per file per cycle.

## Consequences

One failed call per 30 minutes (about 48 a day) instead of about 8,000 while the backend refuses. Rollback: `docker service rollback main-maintenance_vault-sync`.

## Verification

`tests/test_vault_sync_backend_refusal.py`: 401/402/403/429 end the cycle after one call; a 500 skips only that file. Live: spend-log rate of the `python-httpx` caller after deployment.
