# gwbridge ingress DNAT remediation

Host-level replica of the upstream fix for [published ports unreachable from containers](docker-29-8-published-ports-unreachable-from-containers.md), kept until the engine carries the fix.

## Design

- A dedicated nat chain holds one DNAT rule per ingress-published port: match the `docker_gwbridge` input interface and a local destination type, then `DNAT --to-destination <ingress gateway>:<port>`.
- One jump to that chain is inserted at the top of `PREROUTING`.
- Only the ports that need it are listed. Add a port after proving it times out from a gwbridge container and that the rule fixes it.
- A systemd oneshot ordered after (and part of) `docker.service` applies it, plus a short timer that reconciles when Docker rebuilds its chains. Applying twice leaves exactly one jump.
- The unit has no capabilities beyond network administration; check with `systemd-analyze security`.

## Rollout that worked

1. Back up the current rules.
2. Arm a rollback timer (see [reversible live network changes](dead-man-switch-for-live-network-changes.md)).
3. Apply one canary port, compare before and after from a gwbridge container, and compare the filter table with the backup.
4. Extend to the other ports, watch the firewall log for new blocks and the affected consumers for a restart-free period.
5. Persist the units and keep the helper in a reviewed repository with a test for its rendered unit template.

## Pitfalls seen

- A redeploy ran the unit's `ExecStop remove` and left the node without the rules for about a minute until the timer recreated them, because a code regression had broken the template. Test the rendered unit and keep the reconcile timer short.
- Take the xtables lock around rule edits and verify `remove` really removed the rule.
- Keep jump ordering explicit; a rollback that the timer immediately undoes is not a rollback, so the rollback must stop the timer.

## Removal

Delete the units and helper when the node runs an engine release with the upstream rule; the helper can detect the upstream rule and disable itself.

## Related

- [Docker gwbridge return routing](docker-gwbridge-return-routing.md)

Entities: [[Docker Swarm]]
