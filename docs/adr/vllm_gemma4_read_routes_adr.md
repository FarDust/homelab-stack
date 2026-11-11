# vLLM Gemma on demand: reads, model list and readiness

## Context

`vllm-gemma4` scales to zero through Sablier (`sablier.group=vllm-inference`). Traefik puts the `load-vllm@file` blocking middleware in front of it, with a 15 minute session and a 15 minute blocking timeout. A single router matched every request to the host, so any request started a session and scaled the service to one replica.

The Traefik access log, which already reaches Loki through the OTLP collector (`{service_name="traefik"} | RouterName="vllm-gemma4@swarm"`), showed for 2026-11-03 to 2026-11-11:

- every request to the router was `GET /v1/models`, one every 5 minutes, from a client that sends no User-Agent and sits behind the Swarm ingress;
- no `POST` and no other path;
- the 109 answers with status 200 on 2026-11-04/05 have `OriginStatus` 0 and an empty body, so no backend answered them; the engine never answered a request in the window.

Each poll renewed the session, so the service never stayed at zero, and Swarm restarted the failing engine in a loop on the GPU node.

The engine never finished loading. The last failed task (2026-11-11 03:37-03:44 UTC) stopped with `torch.OutOfMemoryError: Tried to allocate 56.00 MiB ... 21.93 GiB is free` inside `UVAOffloader._maybe_offload_to_cpu`, with an impossible "Process 1 has 17179869184.00 GiB memory in use". The checkpoint weights are 32.6 GB in four safetensors shards, more than the 31.84 GiB card, so `--cpu-offload-gb` is required. On WSL vLLM 0.19 already disables pinned memory and therefore UVA (`is_uva_available()` returns `is_pin_memory_available()`, which is false under WSL), so the copy offload path was the one failing. The cause of that allocation failure is open; a candidate is the WSL GPU paravirtualisation layer, whose `dxgk_create_allocation` failures were logged in the guest during the same restart cycles.

Sablier v1.8.5 reports a Swarm service ready when its running tasks equal its desired tasks. The engine had no healthcheck, so its task counted as running as soon as the container started, minutes before vLLM listened, and Sablier released held requests too early.

## Decision

1. `vllm-gemma4-models`, a static nginx responder, answers `GET`/`HEAD` on `/v1/models`, `/v1/models/` and `/v1/models/<id>` with the OpenAI list for the served model, at priority 200, whether or not the engine runs. It stays off ephemeral nodes and outside Sablier.
2. Other reads (`/health`, `/metrics`, ...) use the `vllm-gemma4-read` router (priority 100, no middleware): they answer 5xx while the engine is cold and never wake it.
3. The `vllm-gemma4` router keeps the host-only rule, `load-vllm@file` and priority 10, so every other method, inference included, wakes the engine.
4. The engine has a healthcheck on `/health` with a 14 minute `start_period`, below the 15 minute Sablier session and blocking timeout, so its task counts as running only when it serves and Sablier holds requests until then.

## Alternatives

- Pass `/v1/models` through to a cold engine: rejected; clients would see the model disappear whenever it is idle.
- Put the static responder behind Sablier: rejected; the only caller polls every 5 minutes, so a session of 5 minutes or more never scales it down and a shorter one creates about 6 tasks per 30 minutes, which trips `swarm_task_churn` (`docs/adr/workload_churn_log_storm_alerts_adr.md`).
- A Traefik plugin for static responses: rejected; Traefik has no built-in static response and a plugin adds a dependency where the stack already runs nginx for the same purpose.
- Split by inference path prefixes: rejected; every vLLM inference endpoint is `POST` and every read endpoint is `GET`.
- Disable a gateway health check: the gateway was not the caller (no Gemma traffic in its spend logs, no health-check settings, no `/health` or `/models` calls in its logs).
- `VLLM_WEIGHT_OFFLOADING_DISABLE_UVA=1`: rejected; on WSL UVA is already off, so the variable changes nothing.
- Longer Sablier windows for `vllm-inference`: deferred; it changes the Traefik file-provider middleware and needs a measured load time first.
- A smaller checkpoint that fits without offload (a 4-bit 31B build or the MoE variant), or native Linux on the GPU node: open.

## Consequences

- `/v1/models` always lists `gemma-4-31b-it-nvfp4`; the list must follow the engine command, which the tests enforce.
- `/v1/models` answers 200 while the engine is cold or still loading. A client that waits for that 200 before warming the engine will see the model as ready and then wait for the cold start on its first inference call.
- A cold engine answers `/health` with 5xx, which is its real state.
- A load longer than about 14 minutes cannot complete: the healthcheck grace ends, and at 15 minutes Sablier drops the held request and lets the session expire, which scales the engine back to zero.
- After `start_period`, Swarm stops a task whose healthcheck fails and counts it as failed, which feeds `restart_policy` (on-failure, 3 attempts per window) and the `swarm_task_churn` alert.
- The first request after idle waits for the load and can also exceed LiteLLM's 600 s timeout.
- Memory budget: the nginx task is limited to 64 MB; Swarm exposes no per-task swap control and the responder needs none.
- Loading still uses host memory on the desktop GPU node; load tests run only with host commit headroom.

## Verification

- `tests/test_vllm_gemma4_read_routes.py` pins the routers, priorities, the catalogue against the engine command, the responder staying out of Sablier, and the healthcheck grace against the Sablier window read from `stacks/main/configs/traefik/static_conf.yml`.
- After deployment: `GET /v1/models` answers 200 with the list through the public host; `/health` answers 5xx through `vllm-gemma4-read@swarm`; Sablier logs no new session for either; the engine stays at its declared zero replicas.
- Pending: an inference `POST` through LiteLLM starting a session, the healthcheck passing and the request being served, in a load test with enough host memory headroom; and the cause of the offload allocation failure.

## Rollback

Remove the `vllm-gemma4-models` service and its config, the `vllm-gemma4-read` labels, the router priorities and the engine healthcheck, then redeploy both services with `uv run cluster-utils deploy service`.
