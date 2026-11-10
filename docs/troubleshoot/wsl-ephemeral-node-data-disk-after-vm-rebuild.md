# WSL-hosted ephemeral node: the data disk after a VM rebuild

A Swarm node that runs inside WSL 2 is ephemeral by label (`node.ephemeral=true`). Its VM can be recreated at any time (a guest kernel panic, `wsl --shutdown`, a host event), and the new VM starts without the extra data disk that holds the Docker root.

## What happens

1. The VM is rebuilt within seconds; the Linux distro starts.
2. The data disk attached to the previous VM (a VHDX attached with `wsl --mount`) is not attached to the new one.
3. `docker.service` fails on its mount dependency (the bind of the data directory), so the Swarm node stays Down until something re-attaches the disk.
4. The manager shows the node Down and reschedules its replicated services; node-local volumes on that node stay unreachable ([node-local state pinning](../adr/node_local_state_pinning_adr.md)).

## Guard design

- Trigger on state (distro running and the disk's filesystem UUID not mounted), not on a timer or a VM id, so any rebuild cause is covered.
- Attach through the same task that normally does it at logon (an elevated scheduled task a normal token may start), then verify the UUID inside the guest.
- Treat a failing guest exec as unknown, not as proof the disk is unmounted ([exec failure is not guest down](wsl-exec-failure-is-not-guest-down.md)).
- Budget the attempts and end in a review marker when the attach task is stuck.

## Placement consequence

Do not pin stateful services to the ephemeral node unless their data is archived elsewhere; see the labels in [node labels](../node-labels.md).

## Related

- [WSL MTU and Tailscale black hole](wsl-tailscale-mtu-black-hole.md)

Entities: [[Docker Swarm]], [[Gabriel-PC]]
