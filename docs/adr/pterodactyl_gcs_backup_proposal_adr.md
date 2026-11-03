# Native Pterodactyl object-storage backups

## Context

Live game data and the mod's differential backup chain require local storage. Wings creates a temporary archive before uploading it. A live-world archive alone does not establish that a Minecraft world can be restored consistently. A separate completed mod backup chain supplies a recoverable world snapshot.

## Decision

Use the Panel's built-in S3 backup adapter against an S3-compatible object-storage endpoint. Scope a dedicated interoperability credential to the server's object namespace and hold it through the existing trust service; supply the Panel configuration as a Docker secret. Keep live game data local and place only Wings backup staging on a dedicated capacity-monitored disk. Keep the completed mod backup chain in the archive and ignore incomplete files. Use Panel's native daily schedule and backup limit; configure prefix-scoped lifecycle rules for noncurrent object versions and account for soft-delete retention.

Parameterize deployment-specific storage and secret identifiers in the host's protected runtime configuration. Preserve unrelated bucket lifecycle rules. Retain pre-upgrade database and application-key recovery material in the approved private custody location.

## Alternatives

A separate uploader or a FUSE mount adds another scheduling or acknowledgement boundary. The native S3 adapter was selected after multipart upload, scoped access and signed readback were tested. A raw live-world backup without a completed mod chain does not provide the same recovery evidence.

## Consequences and verification

The Panel and Wings releases are pinned by digest. Validate stack rendering and actual service mounts before rollout, then prove backup completion, a fresh cloud readback with checksum, integrity of the embedded mod chain and an isolated restore. Verify automatic scheduling separately from a manual schedule execution. A successful extraction is not proof that Minecraft will boot with the recovered world. Monitor staging capacity, the mod's local retention and cloud version/soft-delete growth; a size limit alone may not bound an oversized single full mod backup. Keep deployment-specific evidence and exact rollback material in the private operations record.

The host runtime must define `PTERODACTYL_PANEL_STORAGE_BUCKET`, `PTERODACTYL_PANEL_DB_SECRET`, `PTERODACTYL_DB_ROOT_SECRET`, and `PTERODACTYL_PANEL_DOTENV_SECRET` before rendering.
