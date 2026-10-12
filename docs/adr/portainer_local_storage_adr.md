# Portainer data on a local volume on the Swarm leader

- Status: accepted, applied 2026-10-12
- Owner approval: Gabriel gave full latitude over Portainer on 2026-10-12

## Context

`main-traefik_portainer` crash-looped from 2026-10-11 with `panic: assertion failed: Page expected to be: 470`, which means its BoltDB file `portainer.db` was corrupt. `/data` was the rclone volume `portainer_data` (`gcs:<bucket>/portainer/data`, `vfs_cache_mode: full`): a memory-mapped, fsync-dependent single-file database on a FUSE mount whose cache uploads to object storage asynchronously. The corruption followed the rclone docker plugin deadlock and the memory thrashing on the nodes (2026-10-07 and 2026-10-11).

No usable backup existed: the bucket has no object versioning, and the only older copy (`portainer/portainerdata/portainer.db`, 2025-06-17) was a near-empty earlier instance. Portainer's state is its own settings (admin user, endpoint, registries). Everything it shows about services, nodes and volumes is read live from Swarm through the agent, so losing that state loses no cluster data.

## Decision

Portainer's `/data` moves to the local volume `portainer_local` (`main-traefik_portainer_local`, local driver) on the leader, where the service is already pinned (`node.role == manager`, `node.labels.swarm.leader == true`). Portainer runs as a single replica on that node only. The corrupt file is preserved at `gs://<bucket>/portainer/corrupt-20261011/portainer.db`. Portainer started fresh with the existing `portainer_admin_password` secret and the agent endpoint (`-H tcp://tasks.agent:9001`).

## Alternatives

- **Keep the rclone volume and restore a backup:** rejected. No usable backup existed, and the failure mode remains.
- **Postgres backend:** not available in Portainer CE (BoltDB only, as of 2026-10).
- **A network disk (NFS or block) for Portainer:** unnecessary. The state is reproducible and the service is pinned to one node.
- **Replace Portainer:** deferred. Candidates if this setup still proves fragile: Swarmpit, Komodo (Dockge is compose only).

## Consequences

- If the leader role moves to another node, Portainer starts there with an empty local volume and has to be initialised again. That is acceptable because the state is reproducible.
- No backup job covers the local volume. That is acceptable for the same reason.
- The rclone volume `main-traefik_portainer_data` stays on the nodes until someone removes it deliberately.

## Verification (2026-10-12 ~04:35 UTC)

- `docker service ls`: `main-traefik_portainer 1/1`.
- Service mount `[{"Type":"volume","Source":"main-traefik_portainer_local","Target":"/data"}]`, local driver.
- `https://portainer.<domain>/api/system/status` returns HTTP 200.
- API login with the admin secret succeeded. One Swarm endpoint (type 2, status up), swarm ID present, 4 nodes listed.
- Applied live with `docker service update --mount-add`. In a single update, `--mount-rm /data` combined with `--mount-add ... target=/data` dropped the mount entirely, so the add was run as a separate update. The compose file now matches the live spec, and a later `main-traefik` stack deploy is a no-op for this mount.

## Proposed improvements (not applied)

- Pin `portainer/portainer-ce` and `portainer/agent` to a version tag instead of `latest`.
- Put the UI behind the cluster's SSO forwardAuth, as with other admin UIs, and verify it in a browser per AGENTS.md.
- Add a healthcheck on `/api/system/status`.
