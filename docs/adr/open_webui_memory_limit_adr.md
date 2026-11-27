# ADR: Open WebUI memory limit of 3 GiB with a 768 MiB reservation

Date: 2026-11-27 (10:45 Chile, UTC-3)

## Context

`llms-governance_open-webui` (image `ghcr.io/open-webui/open-webui:v0.11.0`, 2 replicas,
`load.tier == heavy`, stop-first updates) had a memory limit of 8 GiB. Prometheus (cAdvisor)
over 7 days, measured 2026-11-27 about 13:30 UTC: working set peaks at 644 MB per replica and
usage plus swap peaks at 1,245 MB. On frost-fang one replica holds about 1.0 GB of swap with a
54 MB resident set: cold pages of an idle UI. An 8 GiB limit lets such a task grow into up to
8 GiB of the node's swap before the cgroup limit applies.

## Decision

Set `limits.memory: 3G` (about 2.4x the 7-day peak including swap) and add
`reservations.memory: 768M`. CPU limit stays at 4.

Swap budget (required by `AGENTS.md`): Swarm exposes no per-task memory-swap setting, so no
swap value is set. Docker's default for a limit without `--memory-swap` applies; the limit
bounds growth of resident memory and the swap a task can accumulate by reclaim, but is not a
hard swap guarantee. `memswap` settings are deliberately not added.

## Alternatives

- Keep 8G: leaves the unbounded growth path.
- 2G: 1.6x the peak; less headroom for document ingestion bursts.
- Restart to drop swap: not allowed outside the rolling update; the cold pages are harmless.

## Consequences

- The benefit is small: current swapped pages are cold and stay until the next rolling update.
- A task above 3 GiB is OOM-killed and restarted by Swarm; a restart cuts in-flight chats.
- The reservation makes the scheduler account 768 MiB per replica on the heavy nodes.

## Verification

After deploy: `docker service inspect --format '{{json .Spec.TaskTemplate.Resources}}'
llms-governance_open-webui` shows the new limit and reservation, both replicas are Running and
the health endpoint answers. Rollback: restore `memory: 8G`, drop `reservations`, redeploy.
