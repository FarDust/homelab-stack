# PR-Agent review service and CI entry point

Date: 2026-11-10

## Context

Gabriel wants PR-Agent (community project, MIT, release 0.49.0) as a primary independent reviewer that uses his ChatGPT subscription through the cluster LiteLLM, with no pay-per-token API key.

## Decision

- Run the official `mosaico_agent` image (A2A 1.0 server) as `devtools-pr-agent_pr-agent`, pinned by digest, internal on the `traefik` overlay, no public route.
- LiteLLM access uses a Trust Agent key (`services/pr-agent/litellm`, 90-day duration, models `chatgpt-subscription-sol` and `chatgpt-subscription-luna` only, no API fallback). Renew by repeating the Trust Agent `provision_service` call with `key_attributes.duration` before expiry (first expiry 2027-02-08).
- The server bearer token is mounted as `.secrets.toml` because dynaconf `@json` env values are not accepted as a mapping by 0.49.0 auth; tokens must match `[A-Za-z0-9._~+/-]+` (no underscore).
- CI calls the service with `scripts/pr-agent-review.py` (A2A `SendMessage`). Exit 0 only for a completed non-empty review; failed tasks exit 1, transport or protocol errors exit 2, so a quota or model failure can never pass a gate.

## Consequences and open items

- The ChatGPT subscription window is shared with all automation; on 2026-11-10 it was exhausted until about 2026-11-12 (HTTP 429 `usage_limit_reached`), so no live review was possible. `/health` is a live LLM probe and returns 503 while the quota is empty.
- The cluster has no CI runner. A job must run where it can reach `devtools-pr-agent_pr-agent:9000`; until a runner or a tailnet route exists, the script runs from a cluster session.
- PR-Agent reads pull requests with a GitHub token that is not provisioned yet.
- One PR-Agent run does not replace the two fresh independent read-only contexts required by the fallback review contract.

## Verification (2026-11-10)

Service 1/1 healthy; card 200 without credentials; `/health` 401 without a token. Script against the service with an inline diff: authenticated, task reached `TASK_STATE_FAILED` (quota), exit code 1 and an explicit message.
