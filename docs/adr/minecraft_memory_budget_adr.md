# ADR: Game server memory has no hard limit, and stays under 16 GiB

Date: 2026-11-13 10:00 UTC

## Context

The Minecraft server (Enigmatica 10, NeoForge 1.21.1, Java 21) runs under Pterodactyl Wings on the 31 GiB build worker, next to CI jobs and Swarm services. The owner's requirement (2026-11-13): the game server has no memory limit that makes the kernel kill or throttle the container, yet it must never use more than 16 GiB.

State measured on 2026-11-13 09:25 UTC, server up since 2026-11-11 03:28 UTC, zero players online:

- Pterodactyl allocation `memory` is 0 (`SERVER_MEMORY=0`, `P_SERVER_ALLOCATION_LIMIT=0`). The container has no cgroup limit: `HostConfig.Memory=0`, `MemorySwap=0`, `memory.max` and `memory.swap.max` are `max`. The requirement "no hard limit" already holds.
- The only ceiling is the JVM heap, set by the ServerStarter config in the server volume (`maxRam: 12G`, `minRam: 6G`, rendered as `-Xmx12G -Xms6G`) with Aikar's G1 flags and `-XX:+AlwaysPreTouch`. Nothing bounds metaspace, code cache or direct buffers.
- Resident set of the JVM: 3.0 GiB in RAM plus 4.9 GiB swapped out (`VmRSS` 3,063,036 kB, `VmSwap` 4,900,224 kB), about 8 GiB in total. The host had 13 of 15 GiB of swap in use, so the kernel evicted the idle part of the heap, not the hot part.
- Netdata cgroup history over three days (anonymous memory of the container): maximum 8.9 GiB resident. cAdvisor does not label this container, so Netdata's `netdata_cgroup_mem_MiB_average{dimension="anon"}` is the series used. Its `swap` dimension reads 0 for this cgroup and is not trusted; `memory.swap.current` in the cgroup is the swap source of truth.

Worst case under the current flags is heap 12 GiB plus roughly 2.5-3 GiB of non-heap memory (metaspace for a large modpack, code cache, direct buffers, GC remembered sets, thread stacks), which is 14.5-15 GiB. That is under 16 GiB with a thin margin and no enforcement.

## Decision

1. Keep Pterodactyl `memory` at 0 and the container without a cgroup limit. A cgroup limit is the mechanism that makes the kernel kill or throttle the process, which the requirement excludes.
2. Bound total use from inside the JVM, which degrades to GC pressure instead of an OOM kill. In the server volume's `server-setup-config.yaml`: `maxRam: 11G` (was 12G), `minRam: 6G` unchanged, and added flags `-XX:MaxDirectMemorySize=1G`, `-XX:MaxMetaspaceSize=512m`, `-XX:ReservedCodeCacheSize=256m`. Worst case is then 11 + 0.5 + 0.25 + 1 + GC and stacks of about 1 GiB, about 13.8 GiB, with roughly 2 GiB of margin to the 16 GiB ceiling. `-XX:MaxRAMPercentage` is not used: with no cgroup limit it would be computed from the host's 31 GiB.
3. Alert `MinecraftServerMemoryNear16G` when the container's anonymous memory stays above 15 GiB for five minutes (`stacks/main/configs/prometheus/alert.rules`, test in `tests/prometheus/node-retention-and-minecraft-alerts.test.yml`).
4. The change takes effect at the next start. Applying it never restarts the server: rule 1 (no restart or disconnect with players online) holds, and a restart with zero players is allowed.

Applied on 2026-11-13 with zero players online (re-checked from `latest.log` immediately before each power action):

- 09:26 UTC: `server-setup-config.yaml` edited in place (original kept as a backup on the node).
- 09:46 UTC: a Pterodactyl `restart` did **not** apply it. The ServerStarter wrapper (`java -jar serverstarter-2.4.1.jar`, the container's main process) reads the YAML once at its own start and relaunches the Minecraft JVM itself ("Restarting server in 10 seconds"), so the new JVM came back with the old `-Xmx12G`. The Wings restart then held the power-action lock, waiting for a container exit that never came.
- 09:52 UTC: console `stop` (the JVM saved and exited), then a Wings `kill` inside ServerStarter's 10-second relaunch window, when only the wrapper was running. Wings completed its pending restart by starting a fresh container process. The new JVM runs `-Xmx11G -Xms6G` with the three bounding flags, `memory.max` stays `max`, and `Done (15.1s)` was logged at 09:54:16 UTC (2 minutes 8 seconds after the kill).
- Resident set at the end of boot: 7.8 GiB, swap 0 (`AlwaysPreTouch` touches the 6 GiB initial heap at start). Host swap used fell from 16.2 GiB to 13.4 GiB, because the previous JVM had 4.9 GiB of its heap swapped out.

A configuration change to the JVM flags therefore needs a container restart, not only a server restart: stop the server, then end the wrapper during its relaunch window (or kill the container from the panel while the JVM is not running), and let Wings start it again.

## Alternatives

- **Pterodactyl memory limit of 16 GiB.** Rejected: a hard cgroup limit kills the container at the ceiling and Wings reports it as a crash.
- **`-XX:MaxRAMPercentage`.** Rejected: meaningless without a cgroup limit.
- **Leaving 12G.** Rejected for lack of margin; the measured peak is far below it, so 11G costs nothing in practice.
- **Dropping `AlwaysPreTouch`.** Not changed: it keeps the heap resident, which helps tick latency when the host is not swapping; revisit if boot-time swap pressure shows up again.

## Consequences

- At the next zero-player restart the JVM starts with `-Xmx11G` and the bounded non-heap areas. Verify with `ps -o args` on the java process and, after a day, with the Netdata anonymous-memory series and `/proc/<pid>/status` (`VmRSS`, `VmSwap`).
- A `java.lang.OutOfMemoryError: Direct buffer memory` or `Metaspace` in `logs/latest.log` means a bound is too tight: raise that single flag, keeping the sum under 16 GiB.
- The alert measures resident memory. Swapped-out pages are not counted by Netdata; the host swap alert `HostLowSwapAvailable` covers that side.

## Verification

- `promtool check rules` and `promtool test rules` pass for the new alert.
- Configuration check after the next start: process arguments, `memory.max` still `max`, resident memory under 15 GiB for a day.
- Rollback: restore the original `server-setup-config.yaml` values (`maxRam: 12G`, remove the three added flags) and restart with zero players.
