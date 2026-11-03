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
