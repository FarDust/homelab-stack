# ADR: Explicit swap budgets for memory limits

Date: 2026-10-11 20:05 UTC

## Context

The cluster uses a mix of Docker Swarm service limits and host-level systemd controls. Recent Netdata remediation proved that limiting resident memory without bounding swap can still leave a host with large swap pressure. Operators need a canonical rule that separates resident memory from swap and prevents future memory budgets from silently inheriting unlimited or excessive swap behavior.

## Decision

Every new memory budget must state both the resident memory budget and the swap budget. For systemd services, use `MemoryMax`/`MemoryHigh` for resident charged memory and `MemorySwapMax` for swap. For cgroup v2, treat `memory.max` and `memory.swap.max` as separate controls. If swap should be denied, say so explicitly with a zero swap budget.

Docker Swarm service resources do not expose a supported per-task memory-swap control. Standalone Docker `--memory-swap` is a RAM+swap total, and omitting it with `--memory` normally allows swap equal to RAM; that behavior must not be presented as a Swarm per-task swap limit. Any Docker daemon `cgroup-parent`, parent slice, node swap size, service placement, or `vm.swappiness` change is a node-level proposal requiring staging and explicit approval. Parent slice and parent cgroup limits are aggregate limits across descendants, not service-specific guarantees. `vm.swappiness` changes reclaim behavior but are not hard limits.

For Netdata, `dbengine` retention-size settings are soft targets and cache settings are not total-memory hard caps. Current docs also specify a minimum 256 MiB per tier. On pressured hosts, proposals must include both page-cache RAM and disk-retention budgets and must avoid treating `dbengine page cache size` as the whole Netdata memory budget.

## Consequences

Existing services are not automatically capped by this ADR. New or changed budgets must document swap explicitly, and operator guidance must distinguish configuration success from runtime recovery such as DB health, plugin state, or backup health.

For the 2026-10-11 Netdata stable rollout, the manager and Frost child-agent
`MemoryMax=768M` target was superseded after runtime OOM evidence. Frost had 14+
automatic OOM restarts at 3-4 minutes, and the manager kernel reported
`CONSTRAINT_MEMCG` OOMs at 21:27:04, 21:47:18, and 21:56:32 UTC. The approved
next source canary is `MemoryMax=1G`, no effective `MemoryHigh`,
`MemorySwapMax=0`, and `OOMScoreAdjust=500` on manager and Frost, pending at
least 30 minutes of observation. WSL remains at its already healthy `1G` profile.
This ADR records the approved canary state, not a canary pass.

## Alternatives

1. Rely on `MemoryMax`/`memory.max` alone. Rejected because resident memory limits and swap limits are separate controls, and recent Netdata pressure showed swap can remain a host-level failure mode.
2. Use Docker Swarm service resource limits as if they exposed standalone Docker `--memory-swap`. Rejected because Swarm does not provide a supported per-task memory-swap knob.
3. Apply a parent slice or Docker daemon `cgroup-parent` globally. Deferred because parent cgroup caps are aggregate controls across descendants and need staging before use on mixed host workloads.
4. Tune only `vm.swappiness`. Rejected because swappiness influences reclaim behavior but is not a hard swap limit.

## Verification

For host systemd drop-ins, keep a source test that asserts exact memory and swap directives and rejects unrelated service overrides. For Swarm monitoring changes, validate Prometheus rules with `promtool` and deploy only the service that owns the changed config.
