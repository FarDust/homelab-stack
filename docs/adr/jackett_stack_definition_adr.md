# Jackett stack definition

Date: 2026-10-13

## Context

`hobby-streaming_jackett` was deployed by hand and never had a definition in the compose repository. On 2026-10-13 it was pinned live by label to the storage-manager node (frost-fang) because the four configured indexers (1337x, limetorrents, thepiratebay, torrentgalaxyclone) exist only in the `/config` volume on frost-fang; the copies on gabriel-pc-wsl and fardustdev hold none (see `node_local_state_pinning_adr.md`). Until now the live constraint was the only record, so a rebuild or a redeploy from the repository would have lost the pin.

## Decision

Define `jackett` in `stacks/hobby/streaming.yml`, reconstructed from `docker service inspect hobby-streaming_jackett`:

- Image `lscr.io/linuxserver/jackett:latest@sha256:eef3e1ad...` (the digest that runs), so a future deploy does not change the image.
- Volume `jackett_config` (stack-scoped name `hobby-streaming_jackett_config`, the name already in use), mounted at `/config`.
- Networks `indexer-net` and `traefik-public`, the two the live service uses; Flaresolverr is reached at `http://flaresolverr:8191`.
- Placement `node.labels.site.class != cloud`, `node.labels.storage.manager == true`, `node.labels.swarm.leader != true`, identical to the live constraints (label-only, no hostnames; ephemeral-rebalance skips these).
- Traefik labels for `jackett.${LOCAL_DOMAIN}` as the live service has them; healthcheck disabled as live.
- Environment `AUTO_UPDATE=false`, `RUN_OPTS=`, `PUID`/`PGID`/`TZ` from the stack variables (live values 1000, 1000, America/Santiago).

The change was rendered with `docker stack config` only; Jackett was not redeployed.

## Alternatives

- Pin by hostname: rejected by cluster rules.
- Copy the indexers to every node: rejected, the copies would diverge from the freshest one on frost-fang.
- Drop Jackett in favour of Prowlarr (already in the stack): possible later, but Sonarr and Radarr currently search through Jackett.

## Consequences

- Jackett has one source of truth; the pin survives redeploys.
- It stays unschedulable if no non-leader storage-manager node is Ready.
- The image is still `latest` plus a digest; bumping it is a deliberate edit.

## Verification

`docker stack config -c stacks/hobby/streaming.yml` renders the `jackett` service with the three constraints and the `jackett_config` volume. Remaining: compare `docker service inspect` against the render at the next planned deploy of `hobby-streaming` (expect no task restart).
