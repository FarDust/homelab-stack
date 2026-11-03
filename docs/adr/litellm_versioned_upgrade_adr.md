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
