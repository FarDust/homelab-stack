# vLLM Gemma on demand: reads, readiness and offload

## Context

`vllm-gemma4` scales to zero through Sablier (`sablier.group=vllm-inference`). Traefik puts the `load-vllm@file` blocking middleware in front of it, with a 15 minute session. A single router matched every request to the host, so any request started a session and scaled the service to one replica.

The Traefik access log, which already reaches Loki through the OTLP collector (`{service_name="traefik"} | RouterName="vllm-gemma4@swarm"`), showed for 2026-11-03 to 2026-11-11:

- every request to the router was `GET /v1/models`, one every 5 minutes, from a client that sends no User-Agent and sits behind the Swarm ingress;
- no `POST` and no other path;
- the 109 answers with status 200 on 2026-11-04/05 came from the Sablier middleware (`OriginStatus` 0, empty body); the engine itself never answered a request in the window.

Each poll renewed the session, so the service never stayed at zero, and Swarm restarted the failing engine in a loop on the GPU node.

The engine never finished loading. The last failed task (2026-11-11 03:37-03:44 UTC) stopped with `torch.OutOfMemoryError: Tried to allocate 56.00 MiB ... 21.93 GiB is free` inside `UVAOffloader._maybe_offload_to_cpu`. The checkpoint weights are 32.6 GB in four safetensors shards, more than the 31.84 GiB card, so `--cpu-offload-gb` is required. vLLM 0.19 offloads through UVA views of CPU memory; on WSL it disables pinned memory (`pin_memory=False`), and the UVA view of unpinned memory fails although the GPU has room. `VLLM_WEIGHT_OFFLOADING_DISABLE_UVA=1` selects vLLM's copy-on-forward offload path instead (`vllm/model_executor/offloader/uva.py`, `vllm/envs.py`).

Sablier v1.8.5 reports a Swarm service ready when its running tasks equal its desired tasks. The engine had no healthcheck, so its task counted as running as soon as the container started, minutes before vLLM listened, and Sablier released held requests too early.

## Decision

1. `vllm-gemma4-models`, a static nginx responder, answers `GET`/`HEAD` on `/v1/models` and `/v1/models/<id>` with the OpenAI list for the served model, at priority 200, whether or not the engine runs. It stays off ephemeral nodes.
2. Other reads (`/health`, `/metrics`, ...) use the `vllm-gemma4-read` router (priority 100, no middleware): they answer 5xx while the engine is cold and never wake it.
3. The `vllm-gemma4` router keeps the host-only rule, `load-vllm@file` and priority 10, so every other method, inference included, wakes the engine.
4. The engine has a healthcheck on `/health` with a 20 minute `start_period`, so its task counts as running only when it serves, and Sablier holds requests until then.
5. The engine runs with `VLLM_WEIGHT_OFFLOADING_DISABLE_UVA=1`.

## Alternatives

- Pass `/v1/models` through to a cold engine: rejected; clients would see the model disappear whenever it is idle.
- A Traefik plugin for static responses: rejected; Traefik has no built-in static response and a plugin adds a dependency where the stack already runs nginx for the same purpose (`ollama-fallback`).
- Split by inference path prefixes: rejected; every vLLM inference endpoint is `POST` and every read endpoint is `GET`.
- Disable a gateway health check: the gateway was not the caller (no Gemma traffic in its spend logs, no health-check settings, no `/health` or `/models` calls in its logs).
- A smaller checkpoint that fits without offload (a 4-bit 31B build or the MoE variant): open; it would remove the PCIe offload cost but changes the model.
- Native Linux on the GPU node, where pinned memory and UVA work: out of scope.

## Consequences

- `/v1/models` always lists `gemma-4-31b-it-nvfp4`; the list must follow the engine command, which the tests enforce.
- A cold engine answers `/health` with 5xx, which is its real state.
- The first request after idle waits for the load; it can exceed the 15 minute Sablier blocking timeout or LiteLLM's 600 s timeout, and a retry after the load succeeds.
- Copy offload moves the offloaded weights across PCIe on each forward pass: tokens are slow, acceptable for an on-demand model.
- Memory budget: the nginx task is limited to 64 MB; Swarm exposes no per-task swap control and the responder needs none.
- Loading still uses host memory on the desktop GPU node; load tests run only with host commit headroom.

## Verification

- `tests/test_vllm_gemma4_read_routes.py` pins the routers, priorities, the catalogue against the engine command, the healthcheck and the offload setting.
- After deployment: `GET /v1/models` answers 200 with the list from `vllm-gemma4-models@swarm`; `/health` answers 5xx through `vllm-gemma4-read@swarm`; Sablier logs no new session for either; the engine stays at its declared zero replicas.
- Pending: an inference `POST` through LiteLLM starting a session, the healthcheck passing and the request being served, in a load test with enough host memory headroom.

## Rollback

Remove the `vllm-gemma4-models` service and its config, the `vllm-gemma4-read` labels, the router priorities, the engine healthcheck and the offload variable, then redeploy with `uv run cluster-utils deploy service vllm-gemma4`.
