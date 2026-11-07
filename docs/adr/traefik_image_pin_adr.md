# Traefik immutable image pin

## Context

The Traefik service used the floating `traefik:latest` image reference. A deployment intended only to add network aliases therefore resolved a newer image digest and changed both routing configuration and proxy version in one rollout. The deployment was healthy, but the expanded runtime delta had not been reviewed as part of the routing fix.

## Decision

Pin Traefik to the previously deployed immutable digest in the canonical stack. Configuration-only deployments keep the proxy image unchanged unless a separately reviewed release deliberately updates the digest.

## Alternatives

- Keep `latest` and rely on the currently cached image. This is not deterministic across nodes or deployments.
- Accept the incidental proxy upgrade. This couples unrelated configuration and software changes and weakens rollback evidence.
- Override the image only at runtime. This leaves canonical source drifting from production.

## Consequences

Routine Traefik configuration deployments are reproducible and keep their runtime delta scoped. Traefik upgrades now require an explicit digest change, validation, release note, and rollback plan.

## Verification

The routing regression test asserts both the exact digest pin and the existing isolated-overlay aliases. Canonical stack rendering must preserve that digest, the two aliases, and the unchanged network attachments.
