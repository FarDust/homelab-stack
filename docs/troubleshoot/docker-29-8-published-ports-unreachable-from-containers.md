# Docker 29.8 and later: published ports unreachable from containers on the same node

Since Docker 29.8 a container on a Swarm node can fail to reach a Swarm ingress-published port through the node's own address (for example its Tailscale address), while the same port works from other nodes and from the host.

## Symptom

- Containers that reach a service by the node's published address time out; the same call from another node succeeds.
- Consumers that depend on it restart in a loop (a dashboard failing on its database host name, a gateway timing out on a TLS upstream).
- The host firewall logs `[UFW BLOCK] IN=docker_gwbridge SRC=<container> DST=<node address> DPT=<published port>`.

## Mechanism

The nat `DOCKER` chain DNAT rule for ingress ports is restricted with `! -i docker_gwbridge`, so packets arriving from `docker_gwbridge` are not DNAT-ed to the ingress network. They reach the host input path with the published port as destination, and the firewall drops them. `docker-proxy` listening on the port does not help: the packet is dropped on the input path before the proxy is reached.

Upstream (as of 2026-11-10; verify before relying on it): moby/moby issue 53962, and the fix, pull request 54006 ("DNAT gwbridge packets to ingress ports"), merged for milestone 29.10.0, which was available only as a release candidate then.

## Confirm

1. A container attached to `docker_gwbridge` connects to the node address and published port: it times out.
2. The firewall log shows the block lines above, with a count that tracks the failures.
3. `iptables -t nat -S DOCKER` shows the ingress DNAT rule with `! -i docker_gwbridge`.

Do not read an older block on another port as the same fault without evidence.

## Options

- Host-level replica of the upstream rule: [gwbridge ingress DNAT remediation](gwbridge-ingress-dnat-remediation.md).
- Upgrade to a release that contains the fix, then remove the replica.
- Avoid the name that resolves to the node's own address from containers (overlay aliases), when the naming policy allows it.
- `userland-proxy: false` changes behaviour for every published port and needs its own review.

## Related

- [Docker gwbridge return routing](docker-gwbridge-return-routing.md)
- [Reversible live network changes](dead-man-switch-for-live-network-changes.md)

Entities: [[Docker Swarm]], [[Tailscale]]
