# Internal app-distribution origin (circle 0)

## Context

Android apps built by the owner's repositories need a permanent, self-hosted distribution path. A 52 MB APK sent to a phone
abroad took hours: file transfers between paired devices were cancelled, and a single HTTP stream over a link of about 450 ms
round trip gave 16 to 115 KB/s from a server without Range support. Every release was being repaired by hand.

The owner defined distribution circles (2026-11-18): circle 0 is the private network origin only; circle 1 (the default) adds a
mirror in the app's private source-hosting releases; circle 2 adds a public channel; circle 3 adds an official store. A circle
other than 1 applies only on the owner's explicit instruction or an explicit `distribution_circle: N` line in the `AGENTS.md`
of the repository that builds the APK. The owner wrote the circles as 0, 1, 3, 4; they are recorded here as 0 to 3, to be
confirmed. The application-side decision and the mirror are recorded in the app's own repository; this record covers the
origin, which every circle writes and which is the only channel of circle 0.

## Decision

1. **Format.** The origin is a static, signed repository in the F-Droid format, built by `fdroidserver` (the F-Droid
   project's own tool, through its official container image) on the publisher side. It produces `repo/index-v2.json`,
   `repo/entry.jar` (signed), the v1 index and the APKs. The archive feature is off (`archive_older: 0`) because moving files
   would need deletion on the origin. F-Droid clients and Obtainium read it and update in the background.
   **APKs are never re-signed.** Each APK keeps the Android signing key its own release build used, because Android installs
   an update in place only when the signing key matches the installed app. Only the repository *index* is signed with the
   new repository key; the publisher verifies the APK signer fingerprint before and after publishing.
2. **Service.** Stack `stacks/apps/dist.yml` (`apps-dist`, service `apps-dist_web`) runs the official, digest-pinned
   `nginxinc/nginx-unprivileged` image as UID 101 with a read-only root, dropped capabilities and a small tmpfs. It serves
   two hostnames, both required runtime variables on the existing `websecure` entrypoint with the DNS certificate resolver:
   - `APPS_DIST_HOSTNAME` (read): GET and HEAD only on `/repo/` and `/archive/`; every other path is 404. nginx's static
     handler gives byte ranges (`206`, `Accept-Ranges`), `ETag` and `Last-Modified` on APKs, so clients resume and fetch
     in parallel. Successful APK responses are `immutable` (their names carry the versionCode); a 404 carries no cache
     policy. Index, icon and signature files are `no-cache` with ETag and conditional requests disabled: nginx validators
     are mtime plus size, which two equal-size indexes written within one second could share, and these files are small.
   - `APPS_DIST_PUBLISH_HOSTNAME` (write): nginx WebDAV `PUT` plus a JSON directory listing (`GET`); every other method
     is denied (no `DELETE`, `MOVE` or `COPY`). APKs are create-only: a `PUT` over an existing `*.apk` returns 409. Index,
     icon and publisher-state files may be replaced, which is how a publish or a rollback updates the signed index. The
     existence check and the rename are two steps, so two simultaneous first uploads of the same new APK name are not
     excluded at the server; the single-publisher rule below covers that. Both are behind basic
     authentication whose htpasswd file is a Swarm secret (`APPS_DIST_PUBLISHER_HTPASSWD_FILE`, from the private secrets
     directory). Request temp files live on the data volume, so every PUT lands with an atomic rename.
3. **Exposure.** Both hostnames are names under `${LOCAL_DOMAIN}`, which resolve only through the private network's DNS to
   the edge proxy. No public DNS record, public route, tunnel or published host port is added. No browser SSO middleware is
   attached, because update clients cannot follow a login redirect; the network boundary is the access control for reads,
   and integrity does not depend on the origin (see Consequences). The edge listener is published in Swarm ingress mode, so
   the proxy sees ingress-translated source addresses and an address allow-list on the router cannot tell private clients
   from others; a client-network restriction at the edge is tracked in issue #130 as defence in depth.
4. **Storage.** A named local volume `apps_dist_data` on the storage-manager node class, off the control-plane leader and
   never on an ephemeral node (`docs/node-labels.md`). The volume is mounted on the image directory owned by UID 101 so it
   inherits that owner. Docker's data root on that class sits on the large data disk, not the crowded root filesystem.
5. **Publisher.** The `apps-dist` command (a separate private uv package, Typer/Rich/pydantic-settings, typed ports with
   injected adapters) is the only writer: `apps-dist publish --app <id> --version <semver> --apk <path> [--circle N]
   [--repo-root <building repo>]`. It resolves the circle (argument, then the `AGENTS.md` line, then 1; a wider circle than
   allowed fails; circles 2 and 3 are refusing stubs), inspects the APK with `fdroidserver`, snapshots the origin into a
   private temporary directory, runs `fdroid update`, checks that the new version is indexed with the APK's SHA-256 and that
   the index signer is the expected certificate, and uploads changed files with the publisher state and `entry.jar` last.
   It never deletes, moves or overwrites an APK. A different file under an existing versionCode, or a new versionCode lower
   than the current one, is refused. The internal origin is written first; mirrors receive the same signed APK afterwards.
   - **No-op condition.** A publish changes nothing only when the publisher state is unchanged, the signed index already
     lists that versionCode as the newest version with that SHA-256, and the downloaded `entry.jar` references the
     downloaded `index-v2.json` by its SHA-256. In every other case (including an interrupted earlier run) it rebuilds,
     re-signs and uploads the index. An APK already on the origin with the same bytes is adopted, not re-uploaded.
   - **Index consistency.** `entry.jar` references `index-v2.json` by hash, and the two names are fixed by the format, so
     replacing them is two writes. Between them a client holding the old entry sees a hash mismatch and rejects that
     refresh (it never accepts mixed data); it succeeds on the next refresh. After the last upload the publisher downloads
     both files from the read host and fails unless the entry references the served index and the index lists the new
     version. Recovery from any interrupted publish is to rerun the same command.
   - **Single publisher.** Publishing to this origin is a single-instance action: the named owner is the release CI runner
     recorded in the coordination ledger (no locks). Before the index upload the publisher re-reads the state and index and
     fails if they changed since its snapshot, and the post-upload check above detects a later overwrite only if it runs
     after it; two publishers committing within the same seconds can still lose one release from the index. That release is
     still on the origin and in the state, and rerunning its publish restores it.
6. **Rollback = republish.** Both commands change the signed index: `apps-dist publish` with the APK of a version that is
   already on the origin, and `apps-dist rollback --app <id> --to-version <semver>`, which takes that APK from the origin.
   Either makes the version current again unless it already is current (the no-op condition above): every
   newer version of that app is *withdrawn*, i.e. it stays on the origin but is left out of the signed index, and the
   withdrawal is recorded in `metadata/apps-dist-state.json` (publisher state, never served). Republishing a withdrawn
   version brings it back. Android refuses a lower versionCode over an installed app, so a device that already installed
   the bad version needs a new, higher versionCode (or an uninstall); rollback restores the index for every other client.
7. **Retention.** Files: every APK ever published stays on disk; the publisher cannot delete. Index: every version stays
   listed except withdrawn ones (newer than a rolled-back-to version). Removing files is an administrator operation on the
   node with its own manifest, never reachable with the publisher credential, and it never removes the only copy of an APK.
   Free space on the node's Docker data disk is the limit to watch: at about 50 MB per release, 100 releases are 5 GB.
8. **Clients.** The repository URL is `https://${APPS_DIST_HOSTNAME}/repo`.
   - *F-Droid client*: add the repository as `https://${APPS_DIST_HOSTNAME}/repo?fingerprint=<index key SHA-256>`; the
     client verifies the signed index against that fingerprint.
   - *Obtainium*: add the app with the source overridden to "F-Droid Third-Party Repo" and the URL
     `https://${APPS_DIST_HOSTNAME}/repo?appId=<application id>`. Obtainium keeps only `appId` from the query (a
     `fingerprint` parameter is dropped and the default HTML source finds no release), so it does not check the index
     key; integrity on that path rests on Android's same-signing-key rule and the SHA-256 in the index.
9. **Custody.** The repository index keystore and its password, and the publisher password with its htpasswd hash, are
   created once and held in the deployment's private secrets directory on the manager (the canonical channel for this
   cluster's deploy secrets, mode 0600, never in the public repository), with a mode 0600 working copy on the publisher
   host. Recovery from the manager copy alone is verified (keystore opens with the recorded password and yields the
   published fingerprint). Losing the index key forces every client to re-add the repository with a new fingerprint (the
   APKs and their in-place updates are unaffected); it is never rotated without that plan. Moving custody into the Trust
   Agent (OpenBao) needs a new Trust Agent capability and is open work. Private custody details live in the private
   deployment records.

## Alternatives

- **Object storage (the cluster's single-node S3 service, MinIO, Cloudflare R2) behind the edge.** Range and ETag work, but
  it adds a proxy hop, a second credential model and bucket policy for the same static tree, and the existing S3 service is
  on the same node class with the same single-node durability. Kept as a future backend for the `OriginStore` port.
- **Artifact registries (Harbor-style OCI registries, Sonatype Nexus, a hosted artifact registry).** Built for container or
  package ecosystems; Android clients do not speak them, so an F-Droid index would still be needed on top. Heavier to run.
- **A cloud object store or CDN with a public URL (for example a worker in front of R2 with a token).** Fast abroad, but it
  publishes outside the private network, which only circles 2 and 3 allow. Rejected for circle 0.
- **Device-to-device transfers, ad-hoc HTTP servers, peer-to-peer.** Failed in practice (cancelled transfers, no Range).
- **SFTP or rsync accounts on the node.** A host-level account outside the canonical compose workflow; the WebDAV write host
  keeps the write path inside the declared service with one least-privilege credential that cannot delete or replace APKs.
- **F-Droid archive and quarantine moves.** Keep the served index short, but need DELETE or MOVE on the write host; rejected
  so the publisher credential can never remove data. `CurrentVersionCode` alone was also rejected for rollback: the v2 index
  does not carry a suggested version, so v2 clients would still pick the newest file.
- **Firebase App Distribution, Play internal testing.** Third-party control of a private app's binaries; rejected for
  circle 0, reconsidered only for circle 3.

## Consequences

- Integrity does not depend on the origin: Android installs an update only with the same signing key as the installed app,
  the index is signed by a key that never reaches the origin, and the index lists each APK's SHA-256. A stolen publisher
  password can add new files and replace index, icon and state files, but cannot replace or delete an APK and cannot
  produce an index or an APK update that clients accept. The worst case is a broken index, repaired by republishing.
- The volume is node-local: losing the node loses the served tree until it is republished. APKs of circle 1 and wider also
  exist in the mirror; circle 0 APKs exist only here and in the app's build output. **No circle-0-only app may depend on
  this origin until the volume backup in issue #127 is verified by a restore.** Circle 1 apps are covered by the GitHub
  Releases copy.
- Memory budget: 16 MiB reservation, 64 MiB resident limit, one CPU; Swarm has no per-task swap limit, so no
  RAM-plus-swap promise is made.
- One replica with `stop-first` updates: a deploy causes a short outage, and clients retry.

## Open work

| Item | Owner | Card |
| --- | --- | --- |
| Verified volume backup and restore drill (gate for circle-0-only apps) | Lira (apps-dist lane) | #127 |
| Administrator prune command with a deletion manifest | Lira (apps-dist lane) | #128 |
| Free-space alert for the volume and its Docker data disk | Lira (apps-dist lane) | #129 |
| Client-network restriction at the edge for the read router | Lira, with the edge owner | #130 |
| TechDocs/Backstage files for this repository (pre-existing gap) | unassigned | #131 |
| Index-key and publisher-credential custody in the Trust Agent | Lira (apps-dist lane) | needs a Trust Agent capability |
| Circle numbering (written as 0, 1, 3, 4 by the owner) | owner decision | to confirm |

## Verification

- Render the stack with the required variables; `tests/test_apps_dist_stack.py` checks placement, the read-only methods,
  the separate write host, the secret source and the absence of published ports.
- Placement and free space: the service lands on the storage-manager node; record free space on its Docker data disk.
- After deploy: `https://${APPS_DIST_HOSTNAME}/repo/index-v2.json` answers 200 with a valid certificate from a cluster node
  and from a client on the private network; public DNS has no record for the name.
- Publish a real APK with `apps-dist publish`, confirm it is in the index, `curl -H 'Range: bytes=0-99'` returns 206, a
  multi-connection download is faster than one stream, `jarsigner -verify` passes on `repo/entry.jar`, `apksigner` on the
  downloaded APK reports the same certificate fingerprint as the original build, a DELETE or MOVE with the publisher
  credential is refused, a PUT over an existing APK returns 409, and republishing the previous version makes it current
  again.
- Check the service tasks, the container log and the edge proxy access log for errors.

Private values (host names, the client setup on devices, fingerprints) belong in the private deployment records.
