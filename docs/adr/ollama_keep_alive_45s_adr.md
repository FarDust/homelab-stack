# ADR: Ollama keep-alive of 45 seconds on the high-end GPU node

Date: 2026-11-26 (07:00 Chile, UTC-3)

## Context

`llms-governance_ollama` runs on the ephemeral GPU node (a WSL2 VM on the operator's desktop).
With the default `OLLAMA_KEEP_ALIVE` of 5 minutes and `OLLAMA_CONTEXT_LENGTH=128000`, a resident
`qwen3.5:9b` keeps its large KV cache and runner memory mapped for about 10 minutes after every
chat burst from the alert-formatter caller (10.0.0.2). On 2026-11-26 the Windows host commit
headroom fell to 3.2-5 GB after six bursts in three hours (minimum 3.16 GB at 09:52 UTC), close
to the commit exhaustion that crashed the host on 2026-11-20. Measurements and the full
timeline are in the operator vault learning "vmmemWSL commit swings follow Ollama GPU model
load and unload 2026-11-25".

No `OLLAMA_KEEP_ALIVE` was set for this service in any stack file, `.env` or config file. The
`ollama-text-fallback` service sets its own `30m`, and LiteLLM's unload hook sends
`keep_alive: 0` for vLLM models; both are unaffected.

## Decision

Set `OLLAMA_KEEP_ALIVE=45s` on the `ollama` service only. `OLLAMA_CONTEXT_LENGTH` stays at
128000 because callers may need the long context. A per-request `keep_alive` from a caller still
overrides the server default.

## Alternatives

- 30-60 s: equivalent in effect; 45 s sits between them and covers the 2-3 s spacing inside a
  burst with margin.
- Context length 32k: shrinks each load but breaks callers that need the long context.
- A larger Windows pagefile: removes the exhaustion risk, but applying it needs a Windows
  restart, which is ruled out.
- Do nothing: leaves a 3.2 GB headroom floor on the host that crashed on 2026-11-20.

## Consequences

- Callers that chat with gaps longer than 45 s pay a cold load of 1-2.7 minutes each time.
- The host recovers the model's commit about 4 minutes sooner after each burst.
- Only the `ollama` task restarts on rollout (single replica, stop-first); a rollout while a
  request is in flight would cut it, so it waits for a quiet moment.

## Verification

- Container environment shows `OLLAMA_KEEP_ALIVE=45s`; `docker service ps` shows the task running.
- After the next chat burst `ollama ps` shows UNTIL about 45 s ahead instead of 5 minutes, and
  the host `FreeVirtualMemory` returns to its idle level within a few minutes.

## Rollback

Remove the `OLLAMA_KEEP_ALIVE=45s` line from `stacks/llms/governance.yml` and run
`uv run cluster-utils deploy service ollama` on the manager (a single-service update).
