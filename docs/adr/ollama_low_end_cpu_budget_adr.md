# CPU budget for the low-end Ollama instance

## Context

On 2026-11-13 11:36-12:00 UTC (08:36-09:00 Santiago, UTC-03:00) the stable GPU worker `frost-fang` (6 cores, shared with the Minecraft server, Loki, Postgres and the build lanes) showed CPU pressure `some avg10` between 31 and 60 and a load average of 16-20. The top consumer was one process, the `ollama runner` of `llms-governance_ollama-low-end`, at 230-290 % CPU for the whole window. The service had a memory limit (8 GiB) and no CPU limit.

Evidence:

- `ollama ps`: `qwen3.5:2b-q4_K_M`, 3.5 GB, 47 % CPU / 53 % GPU, context 16384. The 3 GB Pascal GPU is shared with `ollama-text-fallback`, so about half of the model runs on the CPU.
- The runner log shows `NumThreads:6`: `OLLAMA_NUM_THREAD` is not a variable Ollama reads, so the intended two-thread cap never applied.
- Traefik access log (Loki, router `ollama-low-end@swarm`): `POST /api/chat` rose from 2-8 per 15 minutes before 11:36 to 42 in the 15 minutes before 12:00, each taking 30 s to 8 min because requests queue behind one model slot.
- Caller: packet capture inside the container shows `User-Agent: litellm/1.106.6` (alias `n8n-chat-low-end`) with the system prompt "AI formatter for homelab alert notifications sent to Telegram", carrying `HostIoPressureSustained` and `HostLowSwapAvailable` alerts. The alert formatter runs on the node whose pressure the alerts report, so load produces alerts and alerts produce load.

## Decision

1. Give `ollama-low-end` the same CPU budget as `ollama-text-fallback`: `deploy.resources.limits.cpus` of `2`. A burst of alert formatting can no longer take more than two of the six cores; the other workloads keep their share.
2. Alert on the missing signal: `HostCpuPressureSustained` (CPU pressure above 0.30 for 30 minutes), next to the existing I/O pressure alert.
3. Keep placement unchanged. The service needs `gpu.class == low-end`, which only this node provides, and the label policy in `docs/node-labels.md` forbids a new label for it.

## Alternatives

- Move the service to another node: no other node has a low-end GPU; CPU inference on the manager is rejected in `litellm_local_text_fallback_adr.md`.
- Lower the context from 16384 so more layers fit on the GPU: likely the larger efficiency gain, but it changes behavior for every consumer of the alias; proposed as a follow-up with a measurement of the alert formatter's prompt size.
- Route the alert formatter to a cloud model only: removes the loop but spends quota on a high-volume, low-value task; the existing fallback chain already reaches Gemini when the local call fails.
- Pin `num_thread` per request: the caller is LiteLLM and the library offers no per-deployment option in the pinned version.

## Consequences

- Alert bursts are slower on the local model (queueing already dominates). The `n8n-chat-low-end` deployment sets no `timeout`, so LiteLLM moves to the Vertex fallback when the call fails or its default timeout expires, not after a short wait: alerts are delayed, not dropped. A per-deployment `timeout` is a follow-up in the LiteLLM config. The Alertmanager receiver is the n8n webhook, which formats with a model; a non-LLM path inside that workflow is not defined in this repository and was not verified in this review.
- The alert reads the real saturation of every node. In the seven days to 2026-11-13 the manager `fardustdev` was above the 0.30 threshold for about 157 of 168 hours, so `HostCpuPressureSustained` fires for it when the rule loads: one alert per node, grouped by alert name, repeated every four hours. Investigate that consumer as its own saturation case rather than raising the threshold.
- The task is replaced once when the change is deployed, so in-flight requests fall back to the next model of their chain.
- Rollback: remove the `cpus` line or raise it and redeploy the stack; the previous service spec is recorded in the deployment report.

## Verification

- `docker stats` shows the container near 200 % at most; `ps` shows the runner within that quota.
- CPU pressure `some avg10` on the node over 15 minutes before and after, with the same alert volume.
- `HostCpuPressureSustained` loads in Prometheus (`promtool check rules`).
