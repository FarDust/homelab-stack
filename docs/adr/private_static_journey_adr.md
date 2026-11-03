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

## Composed PWA release, 2026-11-03

The initial per-file runtime config packaging above is superseded for the composed
PWA. Its complete release contains multiple content-hashed JavaScript chunks,
stylesheets, reference images, offline satellite imagery, icons, a web manifest,
an offline package manifest and its generated service worker. Treating every
asset as a handwritten Swarm config would duplicate the build manifest and create
an incomplete-release failure mode.

Use a versioned application OCI image that copies only the already validated
curated release onto the same official digest-pinned nginx base. This specific
application packaging change is within the owner's authorized cluster deployment
scope. It introduces no new runtime, credentials, identity client or public route.
The public stack requires `JOURNEY_IMAGE` as a tag-plus-digest reference from
private operator configuration; no private registry location belongs in source.
`JOURNEY_VERSION` remains the release identity and nginx config namespace.

The application repository owns the Dockerfile and signed release artifact.
Build and publish on the established remote build worker under the shared build
lock with low CPU/I/O priority. Reuse the approved short-lived registry credential
path and pre-pull onto eligible workers. A cached private image does not establish
autonomous bootstrap on an uncached worker. Keep all existing placement, read-only
root, UID/GID, memory, temporary filesystem, networking and SSO controls.

The nginx config remains a versioned Swarm config. Serve `sw.js` and the offline
package manifest with `no-store`, the web manifest and unversioned files with
revalidation, and only content-hashed assets as immutable. Unknown static paths
return 404 instead of SPA HTML. Verify the exact image digest, source revision,
all package resources, MIME types, cache headers, service worker and real offline
cold launch before accepting the release.

Before cutover, retain the prior canonical stack/config plus targeted runtime
settings. Restore those files and settings for exact application-only rollback;
retain browser-local data and avoid changes to shared infrastructure. The earlier
release files remain usable during this packaging migration.
