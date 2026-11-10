# LiteLLM falls back to a local model for text-only requests

## Context

The gateway's text aliases (`zeus-cheap`, and the new `zeus-text` for the Olympus gods' flavor text) end on paid or quota-limited upstreams: a ChatGPT subscription model, Vertex Gemini and the OpenAI API. When all of them fail, rate-limit or run out of quota, plain text generation stops although a small local model could answer. Tool-calling aliases (`zeus-brain`, `trust-agent-chat`, agents) must not degrade silently to a weaker model: a wrong tool call has side effects, and a wrong sentence does not.

Constraints that shaped the design:

- Cloud spend must stay low: bucket egress is billed, and the Ollama model store is an rclone volume backed by a bucket, so loading a model that is not in the node's VFS cache reads it from the bucket.
- Hosts: the only strong GPU lives on an ephemeral desktop node that is also used interactively; the manager has no AVX (CPU inference is unusable) and little spare RAM; the stable GPU node has 32 GB RAM shared with a game server, six cores with AVX2 and a 3 GB Pascal GPU.
- LiteLLM (pinned 1.106.6) keys fallbacks by model group. Its reliability documentation describes no condition on request content such as `tools`; the only per-request switch is `disable_fallbacks`, per request or per key.

## Evidence: the models that were already installed

Measured 2026-11-10 17:30-17:45 UTC (14:30-14:45 Santiago, UTC-03:00) through the Ollama API of the existing low-end instance, three runs per model, Spanish god-persona prompts of 2-3 sentences, `think: false`, 120 token cap. Host figures are for the stable GPU node.

| Model (existing blob) | Cold load | Warm TTFT | Warm tokens/s | Quality (Spanish persona text) | GCS read on first load |
| --- | --- | --- | --- | --- | --- |
| qwen3.5:2b-q4_K_M (1.9 GB) | 14.5 s | 0.3-0.4 s | 26 | weak: drifts out of persona, awkward grammar | 11 MB (cached) |
| gemma3 4B (3.3 GB) | 63 s (cold), 2.4 s (reload from VFS cache) | 2.5 s | 18-20 | good: in character, fluent, 2-3 sentences | 4.7 GB |
| qwen3.5:4b-q4_K_M (3.4 GB) | not timed in this run | - | - | not scored | 4.7 GB |
| qwen3.5:9b (6.6 GB) | not timed in this run | - | - | not scored | 7.4 GB |

Findings: the existing instance answers well enough, but (1) its weights sit on the bucket-backed volume, and each uncached first load read the whole model from the bucket (16.8 GB in this test, about 0.7 USD at a 0.04 USD per GiB estimate); (2) loading 9B and 4B models pushed the node's load average to about 80 for several minutes, which is unacceptable beside a game server; (3) the same measurement on the ephemeral node read 1.9 GB from the bucket to load the 2B model and drove its load average above 70 together with the 31B vLLM model loading, so it is not a reliable fallback host.

## Decision

1. Serve the fallback from a dedicated Ollama service, `ollama-text-fallback`, with a node-local Docker volume, placed by labels on a stable GPU node (`gpu == true`, `gpu.class == low-end`, `node.ephemeral != true`); no hostname pin. The weights (Gemma 3 4B, about 3.3 GB) are pulled once from the Ollama registry when absent; ingress is free and the bucket is never read. The service has no Traefik route and is reached over the overlay network by service name, so no `*.local` name or alias is involved.
2. Add the model as `local-fallback` (`ollama_chat/gemma3:4b`, 4096-token context, 90 s deployment timeout) and make it the last hop of the fallback chains of text-only aliases only: `zeus-cheap` and `zeus-text`. Chains: primary subscription model, Vertex Gemini Flash, `gpt-5-mini`, `local-fallback`. Retries stay at zero so each failure moves down the chain at once.
3. Enforce the no-tools rule structurally and at runtime. Structurally: no tool-using alias (`zeus-brain`, `trust-agent-chat`, `minecraft-chat`, provider aliases) has `local-fallback` in its chain, and `tests/test_litellm_local_text_fallback.py` fails if one does. At runtime: `text_only_fallback_guard.py`, a pre-call hook, sets `disable_fallbacks` for any request that carries `tools`, `tool_choice`, `functions`, `function_call`, tool-call messages or tool results on a text-only alias (so a tool request that reaches `zeus-text` fails with the upstream error instead of being answered by the local model) and rejects such requests addressed directly to `local-fallback` with HTTP 400. The hook is the only custom code; the library has no content-based fallback condition (documented mismatch), and all routing, retry and cooldown behavior stays in LiteLLM Router.
4. `minecraft-chat` keeps its earlier rule (no local model); its chain is unchanged.

## Alternatives

- Reuse `ollama-low-end` and its bucket-backed volume: rejected, it repeats the egress and load pressure measured above.
- Qwen 3.5 2B on the existing instance: fits the 3 GB GPU and is fast, but its Spanish persona quality was clearly worse; kept available as the manual alternative (`n8n-chat-low-end`).
- Llama 3.2 3B (2.0 GB, Spanish officially supported, about 87M Ollama pulls) as the alternative should Gemma 3 4B prove too slow beside the game server; not measured here.
- The desktop GPU: rejected, the node is ephemeral and its owner uses it interactively.
- CPU inference on the manager: rejected, no AVX and memory pressure.
- vLLM: rejected for a rarely used fallback, it keeps a model resident and its image and startup cost are far larger.
- Conditioning fallbacks natively on `tools`: not offered by LiteLLM 1.106.6.

## Consequences

- Plain-text aliases keep answering when every upstream is unavailable; quality is that of a 4B model and latency is a few seconds (cold start from local disk adds seconds). Persona drift and shorter answers are expected.
- Memory: the service is capped at 5 GiB resident and two CPUs, reserves 512 MiB, and unloads the model after 5 minutes idle; the GPU is shared with the existing low-end instance, so a loaded neighbor makes the model run partly on CPU. Swap is not separately capped (see `2026-10-11-memory-swap-budgeting.md`). The fallback is single-node: if the stable GPU node is down, the chain fails as it did before.
- Egress: pulling the model is ingress; steady-state reads are local disk. The only bucket read this change caused was the benchmarking above, recorded as a one-off.
- Operations: the node-local volume is not backed up (the model is re-pullable). Roll back by restoring the previous `CONFIG_VERSION` configs and removing the `ollama-text-fallback` service; `zeus-cheap` loses only its last hop and `zeus-text` is new.

## Verification

- `tests/test_litellm_local_text_fallback.py`: the local deployment exists; only `zeus-cheap` and `zeus-text` reach it and it is their last hop; no tool-using alias reaches it; guard aliases match the fallback map; the guard disables fallbacks for tool requests and rejects them on the local model; the service uses a local volume, label placement, a pinned digest and no route.
- Live, recorded after deployment in the section below: primary path unchanged; simulated upstream failure answered by `local-fallback` with measured latency; a tool request on a text-only alias does not fall back; the service survives a gateway restart.

## Live verification

Pending deployment.
