# WSL peer and Tailscale: path-MTU black hole

A WSL 2 guest that also reaches the tailnet can lose large packets silently: small packets and TCP connects work, larger ones vanish, so SSH stalls after key exchange and Swarm shows the node pending or Down.

## Mechanism

WSL's NAT networking takes the minimum MTU of all connected Windows interfaces. A Tailscale interface (MTU 1280 or lower, and 1200 on some builds) lowers the guest's `eth0` MTU below the tailnet path's real capacity, while `tailscale0` inside the guest stays at 1280. The mismatch drops packets above the lowest path size.

## Confirm

- DF pings with `ping -M do` at increasing payload sizes: replies up to a size, none above it, while `-M dont` still fails above the same size.
- Compare the same probe to a peer on the same physical endpoint that does not have the problem.
- The manager's TCP session shows a reduced MSS with retransmissions.

## Mitigation

- `net.ipv4.tcp_mtu_probing=1` lets TCP shrink segments on a blackhole; the Swarm node recovered without a rejoin after it was set.
- A durable fix sets consistent MTUs on the Windows adapters or guest interface; record any change and verify with the DF probe.

Keep this separate from WSL command-launch failures (see [exec failure is not guest down](wsl-exec-failure-is-not-guest-down.md)); an MTU black hole explains transport stalls, not a hung `wsl.exe`.

## Related

- [Data disk after a VM rebuild](wsl-ephemeral-node-data-disk-after-vm-rebuild.md)

Entities: [[Tailscale]], [[Gabriel-PC]]
