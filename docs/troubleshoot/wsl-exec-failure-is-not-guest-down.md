# A failing `wsl.exe` exec is not proof the guest is down

`wsl.exe -d <distro> -- <cmd>` can fail with `Wsl/Service/E_UNEXPECTED` or `0x8007274c`, or hang, while the guest is alive, reachable by SSH and running containers. The Windows launch channel and the guest are separate layers.

## Check the layers separately

1. VM: `wsl --list --running`.
2. Guest reachable: SSH over the trusted path (the exec channel may be the only broken part).
3. Docker daemon: `systemctl is-active docker` inside the guest, then the daemon's own socket answering `_ping`.
4. Swarm node: `docker node ls` from a manager. Node Down with the VM running points at the daemon, not at WSL.

## Rules

- A timed-out command that prints empty fields (for example `docker info` with zero containers and exit 124) is an unsuccessful observation, not an empty runtime.
- Two user-owned daemons running in the guest do not show the system Swarm daemon is up; identify the owner of each.
- Probing with `wsl -d X -- cmd` starts a stopped distro, so check state first.
- Record which layer failed in every report and keep the transport failure separate from application health.

## Related

- [Data disk after a VM rebuild](wsl-ephemeral-node-data-disk-after-vm-rebuild.md)
- [WSL MTU and Tailscale black hole](wsl-tailscale-mtu-black-hole.md)

Entities: [[Docker Swarm]]
