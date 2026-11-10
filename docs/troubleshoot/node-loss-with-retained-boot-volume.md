# Node loss with a retained boot volume

A cloud node that vanishes from Compute inventory while its boot volume stays `AVAILABLE` has been terminated, not stopped. Treat it as a rebuild from a retained disk, not a restart.

## Evidence to gather (read-only first)

- Inventory and resource search in every compartment and subscribed region: the instance is absent, not merely stopped.
- The boot volume exists, has no attachment, and has or lacks a backup.
- The provider audit log: a terminate event and its timestamp, and any earlier system-initiated stop events. An audit query window that is too narrow misses a later termination, so widen it before claiming the cause.
- Notifications from the provider: search for an actual termination notice before assuming one exists; unavailable-instance notices for other machines are unrelated.

Absence from inventory does not prove why it was terminated or by whom: a system-grouped event with no principal does not identify a human actor.

## Recovery rules

- Preserve the retained disk and create one protective backup before any launch; reuse that backup instead of creating one per attempt.
- Launch a replacement from the retained disk with a shape that fits the free tier or budget; check network, cost and startup side effects first.
- Keep the node's Swarm and VPN identity where it is still valid instead of forcing a rejoin.
- Distinguish provider `RUNNING` from verified health: SSH, Swarm membership and database reachability are separate checks.
- While the node is offline, report it as unverified in maintenance results; do not reuse an older coverage exception unchanged.

## Related

- [Capacity retry loops need caps](capacity-retry-loops-need-caps-and-fail-closed-state.md)

Entities: [[Docker Swarm]], [[Tailscale]]
