# Wings game-container host prerequisites (machine-id and DNS)

Status: accepted 2026-11-05.

## Context

Wings runs as a Swarm service (`stacks/hobby/gaming.yml`) and creates each game server as a sibling container through the host Docker socket. Two host-level facts broke a Minecraft restart on 2026-11-05:

1. **machine-id bind source.** Wings v1.13 creates a file `/run/wings/machine-id/<server uuid>` and bind-mounts it as `/etc/machine-id` into the game container. Wings wrote the file inside its own container filesystem, while the Docker daemon resolves bind sources on the host. Container creation failed with `bind source path does not exist`, and the server stayed down until the file was created on the host by hand. `/run` is a tmpfs, so a host reboot would remove it again.
2. **Container DNS.** `docker.network.dns` in `/etc/pterodactyl/config.yml` listed only public resolvers (1.1.1.1, 1.0.0.1). Game containers could not resolve internal names under `${LOCAL_DOMAIN}`, for example a bridge or gateway reached over the tailnet. A hand-edited `/etc/hosts` line is lost whenever Wings recreates the container.

## Decision

- Mount `/run/wings:/run/wings` into the Wings service so the file Wings writes is the file the daemon mounts. The host directory is created at boot by a tmpfiles.d entry (`d /run/wings 0755 root root -`, file `/etc/tmpfiles.d/pterodactyl-wings.conf`), because a Swarm bind mount fails when its source is missing.
- Set the Wings `docker.network.dns` list to the tailnet resolver first, then a public one (`100.100.100.100`, then `1.1.1.1`). The same tailnet resolver is already the Docker daemon default on the nodes, so game containers resolve internal names the way every other container does. The file is node-local and holds the Wings token, so it is edited in place and never committed.

## Alternatives

- Per-container `extra_hosts` or a hosts-file edit: not available through Wings, and lost on every recreation.
- `machine_id.enabled: false` in the Wings config: removes the symptom but changes the identity visible to game processes.
- Public DNS records for internal names: leaks topology and breaks the tailnet-only property.

## Consequences

- Wings restarts do not affect running game containers. A game container only picks up the DNS change when it is recreated (stop, then start; a Wings "restart" keeps the same container and environment when the process manager inside restarts the server process).
- After a host reboot Wings can create containers without manual steps.

## Verification

- `docker exec <game container> getent hosts <internal name>` resolves.
- `ls -l /run/wings/machine-id/` on the host shows the server file after a start; no `bind source path does not exist` error in the Wings log.
- Restart the host (or `systemd-tmpfiles --create` after removing `/run/wings`) and start a server.
