# LiteLLM commit-headroom guard runbook

Decision: `docs/adr/litellm_commit_headroom_guard_adr.md`. Code: `stacks/llms/configs/litellm/commit_headroom_guard.py`.

## Signal

- Publisher: memory-guard `publish-headroom` (Task Scheduler task `memory-guard-headroom`, every minute) with
  `MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED=true` in the private memory-guard env file on gabriel-pc. Register with
  `tools/memory-guard/deploy/register-headroom-task.ps1 -ProjectDir <dir> -EnvFile <env>`.
- Check in Prometheus: `memory_guard_commit_headroom_bytes{host="gabriel-pc"}` and
  `time() - memory_guard_commit_sample_timestamp_seconds{host="gabriel-pc"}` (should stay under 90 s).
- File in the guest: `/var/lib/node_exporter/textfile_collector/memory_guard_commit.prom`.

## Flag

- `LITELLM_COMMIT_GUARD_KEY_ALIASES` in the manager `.env`: empty = dark, `commit-guard-qa` = QA key only,
  `n8n` = the n8n automations key, `*` = every key. Optional `LITELLM_COMMIT_GUARD_FLOOR_GIB` (default 6).
- Apply: `source .env && uv run cluster-utils deploy service litellm` on the manager; the service must be re-created
  for env changes (the deploy does that when the spec changes).

## Live verification

1. With the flag on for a QA key only, overwrite the textfile with a synthetic low value and a fresh timestamp
   (as root in the guest, atomically via a `.tmp` file and `mv`); wait one scrape (15 s) and confirm Prometheus shows it.
2. Call a guarded, not resident model with the QA key: expect HTTP 503, `Retry-After: 120`, `COMMIT_HEADROOM_LOW`.
3. Call an unrelated model (for example `local-fallback`) with the same key: expect 200.
4. Restore the real value (or let the next publisher run overwrite it), call a small guarded model: expect 200.
5. Call with a key outside the flag while the synthetic low value is present: expect the guard not to act.

## Disable / rollback

- Dark again: empty `LITELLM_COMMIT_GUARD_KEY_ALIASES` and redeploy `litellm`.
- Fail open while the signal is broken: set `COMMIT_GUARD_ON_UNKNOWN=open` in `stacks/llms/governance.yml` (reviewed
  change) and redeploy.
- Full rollback: `docker service rollback llms-governance_litellm` (previous spec) or revert the PR and redeploy.
- Publisher off: `MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED=false`, or
  `Unregister-ScheduledTask -TaskName memory-guard-headroom -Confirm:$false`.

## Error codes

- `COMMIT_HEADROOM_LOW`: headroom below floor; wait for `Retry-After` or free commit on gabriel-pc.
- `COMMIT_HEADROOM_UNKNOWN`: series absent, stale (over 180 s) or malformed, or Prometheus unreachable; check the
  publisher task, WSL and node-exporter on gabriel-pc-wsl.
- `COMMIT_GUARD_MISCONFIGURED`: a `COMMIT_GUARD_*` value cannot be parsed; the reason names the setting.
