# vLLM Gemma read routes do not wake the engine

## Context

`vllm-gemma4` scales to zero through Sablier (`sablier.group=vllm-inference`). Traefik puts the `load-vllm@file` blocking middleware in front of it, with a 15 minute session. A single router matched every request to the host, so any request started a session and scaled the service to one replica.

The Traefik access log, which already reaches Loki through the OTLP collector (`{service_name="traefik"} | RouterName="vllm-gemma4@swarm"`), showed for 2026-11-03 to 2026-11-11:

- every request to the router was `GET /v1/models`, one every 5 minutes, from a client that sends no User-Agent and sits behind the Swarm ingress;
- no `POST` and no other path;
- during about ten hours on 2026-11-04/05 the engine answered those reads with 200 and the caller still sent no inference request, so it is a model-list poller, not a client that checks before inferring.

Each poll renewed the session, so the service never stayed at zero. When the engine could not load, Swarm restarted it in a loop on the GPU node.

## Decision

Add a read router, `vllm-gemma4-read`, for `GET` and `HEAD` on the same host, with priority 100 and no middleware, pointing at the same service. The wake router keeps the host-only rule, the `load-vllm@file` middleware and priority 10, so every other method (all inference endpoints are `POST`) still wakes the engine.

## Alternatives

- Split by inference path prefixes: rejected; every vLLM inference endpoint is `POST` and every read endpoint is `GET`, so a method split covers current and future endpoints without a path list.
- Disable a gateway health check: the gateway was not the caller (no Gemma traffic in its spend logs, no health-check settings, no `/health` or `/models` calls in its logs).
- Change the caller: it is not identified yet; ingress mode hides its address.
- Longer sessions or Sablier scale mode: keeps the GPU busy for nothing.

## Consequences

- Reads to a cold engine get a 5xx and do not wake it; reads to a warm engine are served.
- A client that waits for a 200 from `/v1/models` or `/health` before sending inference cannot wake the engine. Route such clients through LiteLLM, which lists models from its own configuration.
- Traefik's load-balancer health check reaches the service VIP directly and is unaffected.

## Verification

- `tests/test_vllm_gemma4_read_routes.py` pins the routers, priorities and middleware.
- After deployment, Loki shows the poll on `RouterName="vllm-gemma4-read@swarm"`, Sablier logs no new `vllm-inference` session for it, and the service stays at its declared zero replicas.
- An inference `POST` through LiteLLM still starts a session and scales the service up.

## Rollback

Remove the `vllm-gemma4-read` labels and the router priorities, then redeploy the service with `uv run cluster-utils deploy service vllm-gemma4`.
