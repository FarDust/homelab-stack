# Docker gwbridge return routing with Tailscale

On a node that runs Tailscale with advertised or accepted routes, replies to containers on `docker_gwbridge` can be captured by Tailscale's policy-routing table (the rule at priority 5270 sends lookups to table 52) instead of returning through the bridge. Connections from those containers then time out although the forward path works.

## Fix

Add a policy rule with a priority just below Tailscale's, destination the `docker_gwbridge` subnet, lookup `main`. A small idempotent helper applies it from a oneshot unit and refuses to proceed when `docker_gwbridge` is not the expected subnet or a different rule already holds that priority.

## Probe correctly

Validate only with a container attached to `docker_gwbridge`. A default `docker run` uses the default bridge subnet, which the rule does not cover by design, so its timeout is misleading. State the network of every probe in the evidence.

## Recurrence

The rule is runtime state: it disappears when Tailscale or Docker rebuilds routing. A reconcile timer plus a check that the connected main-table route and the rule both exist catches it. When a recurrence cannot be repaired for lack of non-interactive privilege, the repair is to run the existing helper, not to invent a parallel `ip rule` or to broaden the route scope.

## Related

- [Published ports unreachable from containers](docker-29-8-published-ports-unreachable-from-containers.md): a separate fault with a similar timeout symptom.

Entities: [[Tailscale]], [[Docker Swarm]], [[Docker Swarm Overlay Networking]]
