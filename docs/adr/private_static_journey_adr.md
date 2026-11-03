# Private static journey hosting

## Context
Personal mobile-accessible tools belong on the existing cluster and VPN front door. Publishing the full planner or selecting an external hosting platform does not follow that requirement.

## Decision
Use an official digest-pinned nginx image for a curated static build. The service joins the existing edge overlay, receives no published host port, and uses the established HTTPS plus shared browser SSO middleware. Routing identifiers and release artifact paths are required runtime variables. No new identity client, public tunnel, persistent volume or custom image is introduced.

Mount the versioned index, JavaScript, stylesheet and two reference photos as Swarm configs. Each file must be below the platform config size limit. Artifact acquisition and checksum verification precede deployment. Required environment keys: JOURNEY_HOSTNAME, JOURNEY_VERSION, JOURNEY_ASSET_DIR, JOURNEY_JS_FILENAME, JOURNEY_CSS_FILENAME, JOURNEY_PHOTO_ONE_FILENAME, JOURNEY_PHOTO_TWO_FILENAME. Private values and the application repository mapping belong in private deployment records.

## Alternatives
An external hosted page does not reuse the private infrastructure. A node-local bind mount would couple this stateless service to a particular filesystem. A custom image is unnecessary because the upstream server and runtime configs cover the requirement.

## Consequences
The container runs as UID/GID 101, with a read-only root, dropped capabilities, a 16 MiB temporary filesystem, 8 MiB reservation and 32 MiB resident memory limit. Swarm offers no per-task swap limit, so this does not claim a hard RAM-plus-swap budget. Placement uses the light-capacity label and excludes ephemeral nodes. The current light node is an availability dependency rather than a hard-coded hostname.

## Verification and rollback
Render the canonical stack, verify asset checksums and config sizes, then deploy with cluster-utils. Check container health and successful index/asset responses. In a private browser, verify HTTPS redirects through the existing identity provider. A completed authenticated browser session is required before claiming the full post-login interaction was verified.

For a new isolated deployment rollback, remove only this stack after explicit rollback authorization, retaining its versioned source and artifact; redeploy the same canonical stack and previous release settings to restore. No shared edge, identity, Docker daemon or VPN restart is part of rollback.
