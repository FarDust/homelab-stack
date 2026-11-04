# Versioned LiteLLM upgrades

## Context

The AI gateway stores durable state in PostgreSQL. Container-image rollback does not reverse schema migrations. A floating image tag also obscures which version is running.

## Decision

Pin the LiteLLM 1.106.6 release and immutable image digest. Before upgrading, take and validate a database backup and rehearse the release migrations against an isolated restored database. Keep existing routing and credentials unchanged during the version upgrade.

## Alternatives

A floating image tag was rejected because it does not identify the deployed release. Automatically restoring a database on a failed rollout was rejected because it could overwrite newer production writes.

## Consequences

The upgrade is explicit and auditable; maintaining it requires future reviewed version bumps. Schema rollback and restoration need separately verified procedures. ChatGPT subscription authentication is a separate integration and is not established by this image upgrade.

## Verification

Validate compose, verify image version, restore a database dump into isolated PostgreSQL, rehearse the target migration, deploy only the gateway, and verify readiness plus existing consumer-facing models.

## ChatGPT authentication storage

The gateway uses a dedicated writable node-local Docker volume for the ChatGPT OAuth token directory. Existing placement selects the storage-manager leader, so routine task replacement on that node retains the refreshed file; a node loss does not. This is an interim single-node design, not shared storage or a verified backup. Adding a RustFS-backed volume needs validation of synchronous writes and refresh-token concurrency before it can provide stronger failover. Never place the tokens in the image or source control.

### Subscription model isolation

Explicit `chatgpt-subscription-sol` and `chatgpt-subscription-luna` aliases target the ChatGPT provider and do not fall back to paid API deployments. Their availability depends on the enrolled ChatGPT account. Gateway authorization and OpenAI subscription authorization are distinct. Confirm actual provider and successful request rather than treating a listed model as proof.

On 2026-11-03, after enrolling the gateway account through the device flow, a gateway redeployment retained the token file and both subscription aliases returned HTTP 200 with the expected short response via Chat Completions. This verifies one task replacement on the same node, not automatic refresh, node-failover persistence or backup recovery.

On 2026-11-03 a deliberate live refresh rotated the refresh token and persisted the replacement. After a forced service task replacement, a real subscription request returned HTTP 200. One intervening task failed with exit 3; its logs showed Redis connection timeouts and temporary DNS resolution errors, while a later task recovered. This is not proof of the precise failure cause. The test does not prove survival of storage-node loss.

## Trust Agent subscription fallback

Gabriel requested a ChatGPT-backed reasoning fallback on 2026-11-03 SCL. Preserve the existing local primary and low-end route, then try the explicit ChatGPT Terra and Sol subscription aliases. The low-end alias has the same subscription escape route when invoked directly. LiteLLM Router owns retries and fallback selection; Trust Agent authorization and tool boundaries stay unchanged. API-key routes remain separate and are not used as paid fallbacks. The chain is best effort: subscription exhaustion or provider outage can still fail, and a local reasoning result does not prove tool authorization or successful provisioning. Verify Terra inference and forced low-end failure through the live gateway, plus a harmless tool-call continuation. Config validation and the successful installed-provider SDK probe are prerequisites, not deployment proof.

Verification: the installed ChatGPT provider and the deployed gateway alias both returned OK for gpt-6.1-terra. CONFIG_VERSION 751 deployed and readiness returned 200 after startup. An isolated installed-Router test injected a refused local endpoint and used the configured low-end fallback chain to obtain OK from the real Terra gateway. The proxy intentionally rejects mock-testing request parameters; this guard remained enabled. The Trust Agent credential had an obsolete team alias instead of the existing team UUID. The supported LiteLLM admin API corrected only that association; the key, model allowlist, budgets, limits and expiry were verified unchanged. A subsequent consumer check exposed intermittent container DNS failures for the existing gateway hostname; full consumer tool continuation remains under verification.

Consumer recovery: preserve the Trust Agent key and existing budgets/limits, while explicitly permitting only the Terra and Sol subscription aliases requested by Gabriel in addition to trust-agent-chat. A harmless function call and tool-result continuation with that actual service credential returned 200 and OK. Its isolated trust-internal network had intermittent MagicDNS failures; preserve isolation and TLS/SNI by mapping only the existing LiteLLM hostname to the verified gateway tailnet address in this service, with LITELLM_GATEWAY_HOST_IP as an explicit override. This is a scoped stable-host dependency, not cluster-wide DNS repair. Bound each local inference attempt to 10 seconds and disable retries only for the two Trust Agent local groups, so a stalled local runner yields to the subscription chain. All routes remain best effort.

## Minecraft chat route

Gabriel authorized on 2026-11-04 SCL a low-budget Minecraft chat alias, `minecraft-chat`, following the Trust Agent Terra pattern. The primary is the ChatGPT subscription model `chatgpt/gpt-6.1-terra` (20 second timeout). On failure LiteLLM Router falls back to `minecraft-chat-local` (`ollama_chat/qwen3.5:9b` on the high-end Ollama, 10 second timeout) and then `minecraft-chat-low-end` (same model on the low-end Ollama, 10 second timeout); `minecraft-chat-local` also falls back to `minecraft-chat-low-end`. All three groups use zero retries so a failure moves down the chain immediately. No paid API deployment is in the chain, consistent with subscription model isolation above. The chain is best effort: if the subscription and both Ollama hosts fail, the request fails.

Reply length is controlled by the persona system prompt, not by an aggressive cap. Measured through the gateway on 2026-11-04 with five short Spanish in-character prompts per setting against the same Qwen3.5 family on the low-end Ollama (2B variant, since the 9B variant was not loaded and the other routes were unavailable, see below): with thinking enabled, every one of 15 runs at `max_tokens` 200, 400 and 800 ended with `finish_reason=length` and an empty visible reply (the cap was consumed by hidden reasoning; LiteLLM reported no reasoning-token count). With `reasoning_effort: none`, all 15 runs ended with `finish_reason=stop` and a non-empty reply of 13 to 74 completion tokens (about 1 to 3 seconds). The two Ollama entries therefore set `reasoning_effort: none` and `max_tokens: 400`, about five times the longest observed reply. The ChatGPT Terra entry sets no cap and no reasoning option because it could not be measured: the subscription weekly usage limit was exhausted during the test, the high-end Ollama was unreachable, and the 9B model on the low-end Ollama exceeded the 10 second timeout on a cold load. Measure the Terra route and the 9B entries again, and adjust this section, once they are reachable. Money budgets do not apply to subscription or Ollama routes, which report no per-token cost, so the key for this alias is limited by tokens per minute (`tpm_limit`), requests per minute (`rpm_limit`) and `max_parallel_requests`; suggested values are `tpm_limit` 2000, `rpm_limit` 10 and `max_parallel_requests` 2. A money budget is optional and has no effect on these routes. Restrict the key's model allowlist to the three `minecraft-chat*` aliases. The key is created later through a Trust Agent `provision_service` call; this change creates no key. Tool calling is not part of this route.
