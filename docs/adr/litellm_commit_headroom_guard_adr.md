# LiteLLM commit-headroom guard for cold Ollama loads on gabriel-pc

Status: accepted 2026-11-27. Code: `stacks/llms/configs/litellm/commit_headroom_guard.py`; tests:
`tests/test_litellm_commit_headroom_guard.py`; host signal: `tools/memory-guard` 0.4.0 `publish-headroom`
(`docs/adr/memory_guard_adr.md`, addendum 2026-11-27); runbook: `docs/runbooks/litellm-commit-headroom-guard.md`.

## Context

- Every cold load of a model on the high-end Ollama (`llms-governance_ollama`, WSL guest of gabriel-pc, reached as
  `https://ollama.${LOCAL_DOMAIN}`) raises `vmmemWSL` private commit on Windows by about 10 GB while the model is on
  the GPU (CUDA allocations are charged 1:1 to the VM process). On 2026-11-27 the Windows free virtual memory (commit
  headroom) fell to 2.9, 1.1 (10:53:46Z) and 3.7 GB during loads; commit exhaustion crashes the desktop
  (2026-11-20 incident).
- `OLLAMA_KEEP_ALIVE=45s` (`docs/adr/ollama_keep_alive_45s_adr.md`) shortens residency, so each chat after a gap above
  45 s is a new cold load. On 2026-11-27 08:38-11:05Z there were 12 loads.
- LiteLLM spend logs (`/spend/logs/v2`, 2026-11-26 11:00Z to 2026-11-27 13:00Z) attribute every one of those 12 load
  starts to a `n8n-chat` request from the key alias `n8n` (team `automations`, user agent `langchainjs-openai/1.0.0`)
  with zero attempted fallbacks: the trigger is the n8n automations calling `n8n-chat` directly. The OpenAI
  "no credits remaining" 429s (constant since 2026-11-10/11) are a separate direct `gpt-5-mini` caller and do not fall
  back to the local model.

## Decision

- A LiteLLM `async_pre_call_hook` (`CommitHeadroomGuard`) runs before routing. For a request whose deployments point at
  the guarded Ollama base (`OLLAMA_API_BASE`, plus optional `COMMIT_GUARD_API_BASES`) with an `ollama/` or
  `ollama_chat/` model, it:
  1. passes if every target model is already resident (`GET /api/ps` on `llms-governance_ollama`): no new commit;
  2. reads `memory_guard_commit_headroom_bytes{host="gabriel-pc"}` and
     `memory_guard_commit_sample_timestamp_seconds{host="gabriel-pc"}` from Prometheus;
  3. answers HTTP 503 with `Retry-After` (default 120 s) and an explicit reason (error code, value, floor, sample age,
     code path, flag name) when the headroom is below the floor (default 11 GiB, `LITELLM_COMMIT_GUARD_FLOOR_GIB`).
- Unknown signal (absent series, stale sample older than 180 s, Prometheus failure, malformed or non-finite value)
  fails CLOSED with `COMMIT_HEADROOM_UNKNOWN`; `COMMIT_GUARD_ON_UNKNOWN=open` is the only, documented way to fail open.
- A misconfigured numeric setting refuses only flagged callers' Ollama requests with `COMMIT_GUARD_MISCONFIGURED`;
  deployment-resolution errors pass the request (it may be unrelated) and are logged. Unrelated models (cloud, the
  low-end Ollama, the text fallback) never read the signal and are never blocked.
- Feature flag: `LITELLM_COMMIT_GUARD_KEY_ALIASES` (comma-separated LiteLLM key aliases, `*` for every key). Empty, the
  default, keeps the guard dark. Enable for a QA key first, then the real caller(s).
- Host signal: memory-guard `publish-headroom`, every minute from Task Scheduler, writes the two gauges into
  `/var/lib/node_exporter/textfile_collector/memory_guard_commit.prom` inside the already running WSL guest (never
  starts WSL); the existing global node-exporter (`--collector.textfile.directory`) exports them and Prometheus scrapes
  every 15 s.

## Alternatives

- Traefik middleware on the `ollama@swarm` router: Traefik has no middleware that reads a Prometheus value; it would
  need a custom forwardAuth service (new infrastructure). It would also cover Open WebUI, which reaches Ollama directly,
  but no load on 2026-11-27 came from that path. Rejected for now; revisit if Open WebUI loads appear.
- Ollama-side check: Ollama has no admission hook; an nginx or proxy in front of it is the same custom service.
- Router-level fallback to a cloud model when low (RCA remedy 1/3 variant): spends money; out of the stated budget.
  The pre-call hook runs before routing, so a refusal never triggers the `n8n-chat` fallback chain.
- `windows_exporter` on the desktop: the canonical exporter (prometheus-community, above 3,000 stars) would give
  `windows_memory_*` series, but it is a new Windows service installed on Gabriel's desktop; memory-guard already
  samples the value. Recorded as the follow-up if more host series are needed.
- Unleash (`main/feature-flags`) for the flag: needs the Unleash client inside the LiteLLM image; the key-alias env
  flag gives the same per-caller rollout with no new dependency. Move to Unleash when the hook gains a client.

## Consequences

- Callers of guarded models get 503 + `Retry-After` while the host is short of commit; n8n must retry or fail the
  workflow visibly. Requests to an already loaded model are never refused.
- Not covered: router-internal fallbacks into `n8n-chat` (for example from `gpt-5-chat-latest`), because the pre-call
  hook sees the original alias; the 26 h spend logs show zero such fallbacks. Open WebUI direct traffic is not covered.
- The signal is at most about 60 s + 15 s old; a load that starts above the floor can still push headroom down by
  about 10 GB. The floor is a safety net, not a capacity plan; raise it (for example to 11 GiB) if loads from 6-10 GiB
  still reach exhaustion.
- When WSL is down, the series disappears and guarded requests fail closed, which matches Ollama being down.
- The default floor is 11 GiB (raised from 6 GiB on 2026-11-27, Lira follow-up). The first value, 6 GiB, admitted a
  10 GB load at 6-10 GiB free. Evidence for the change: Prometheus `memory_guard_commit_headroom_bytes` showed a
  minimum of 1.1 GiB on the day and a load adds about 10 GB of commit, so admitting a load needs at least that much
  headroom plus margin. Over the first 24 h of the series the host sat below 6 GiB 25 % of the time and below 11 GiB
  36 % of the time: the raise adds refusals in the 6-11 GiB band and no other behaviour. Rollback is the flag
  `LITELLM_COMMIT_GUARD_FLOOR_GIB=6` plus a litellm redeploy; superseded value: 6 GiB.
- Callers must treat the 503 as a retry signal. The n8n "Notification Forwarder" workflow sends one agent run per
  alert webhook and has no retry on its model node; its alerts during a refusal are lost until the workflow retries
  or falls back (see the n8n learning in the vault).
- A refusal is raised before routing, so the configured `n8n-chat` fallbacks (low-end Ollama, cloud) do not fire; the
  caller sees the 503 directly.
- The publisher checks that the distro runs and then calls `wsl.exe`; if WSL stops in that window `wsl.exe` could start
  it. The window is milliseconds once a minute; accepted and recorded.
- Queries use `min(...)` and `max(...)` so a transient duplicate series (node-exporter reschedule) does not fail
  every request closed; untagged Ollama names match `:latest` in `/api/ps`.

## Verification

- Unit tests: below floor refuses with 503/Retry-After/reason; above floor passes; resident model passes; wildcard
  route guarded; absent/stale/failed/NaN/negative/non-numeric/error-status signal fails closed; fail-open only with
  the setting; dark by default; per-key flag; unrelated models do no signal reads; router errors never block;
  misconfiguration scoped to flagged Ollama requests; gateway wiring.
- Live (2026-11-27): see the runbook for the procedure and the vault note
  `Learnings/gabriel-pc/LiteLLM commit-headroom guard live verification 2026-11-27` for the recorded results.
