# ADR: Staggered start of GPU and AI services on the ephemeral node

Date: 2026-11-10 (21:00 Chile, UTC-3)

## Context

The ephemeral GPU node (`node.labels.node.ephemeral == true`, `gpu.class == high-end`) runs a
WSL2 VM. Every recovery after a VM start brings back all of its Swarm tasks at once: the model
loaders (Whisper, Ollama, ComfyUI, the Jupyter notebook) and the media apps. Operator
observations on 2026-11-10 tie each guest kernel panic (`Fatal local machine check`) to the
minutes after a VM start, when the VM grows from about 1.5 GB to 12-24 GB while the Windows host
commit is at 90-97%. The simultaneous startup memory burst is the best-supported trigger. The VM
limits stay as the operator set them; this change spreads the load instead of shrinking it.

How Swarm behaves, checked against the live cluster and the engine documentation:

- `restart_policy.delay` is counted from the moment the replacement task is created. While the
  node is down the replacement waits unassigned, so the delay is already spent when the node
  returns and the scheduler assigns every pending task in the same second. It staggers later
  failure restarts, not the first start.
- Swarm has no `depends_on` ordering across services and no start-order primitive.
- Resource reservations are checked against the node's advertised memory (16.3 GB for this node)
  and only stop over-commitment; they do not sequence tasks.
- `/proc/uptime` inside a container reports the host (VM) uptime. Verified on a manager node: the
  container and the host printed the same value.
- No startup gate, stagger or boot-storm control existed in the repository.

## Decision

1. A startup gate in each gated service's `entrypoint`: a short POSIX shell wrapper that reads
   the host uptime and sleeps only for the remainder of the service's slot
   (`STARTUP_GATE_SLOT_S`, seconds after VM boot), then `exec`s the original entrypoint with the
   original arguments. After a VM start the services come up one slot at a time; on a routine
   restart or update (uptime already past the slot) the wait is zero. The wrapper uses only `sh`,
   `cut` and `sleep`, which every gated image already ships.
2. Slots, lightest first, at least 45 s apart (seconds after VM boot): whisper 120, ollama 180,
   jellyfin 240, jellyseerr 290, sonarr 340, radarr 390, bazarr 440, qbittorrent 490,
   jupyter-tensorflow 560, comfy-gpu 660.
3. `restart_policy.delay` follows the same order (30 s plus 15 s per rank: 30, 45, 60, ... 165)
   so a crash loop or a failed first start does not re-create the burst. The `max_attempts`
   limits of whisper and comfy-gpu are widened (5 attempts per 10 and 20 minutes) because the
   engine often rejects the first start right after a VM boot.
4. Memory reservations that make the scheduler account for the loaders: comfy-gpu 4G, ollama 2G,
   jupyter-tensorflow 2G, and 256M for each gated media app (whisper keeps its existing 1536M).
   The total stays below the 16.3 GB the node advertises. No limits change.
5. The `whisper` health check `start_period` rises from 120 s to 300 s to cover the gate wait
   plus the model load.
6. `update_config` is unchanged: every gated service is a single replica with the default
   stop-first order, which keeps two copies of a model from loading at once.
7. `vllm-gemma4` is not touched and stays declared at zero replicas.

The `.wslconfig`, WSL limits and host settings are out of scope and unchanged.

## Alternatives

- Restart delays alone: rejected, as explained in the context; they do not delay the first start.
- Swarm generic resources (one "start slot" token per node): a true serializer, but it needs a
  `daemon.json` change and a Docker daemon restart on the node, and the slot is held for the life
  of the task, so it would also serialize steady state.
- A controller that scales services up one at a time after a node returns (an extension of the
  ephemeral-rebalance controller): robust to slot drift and able to wait for observed memory, but
  a new moving part with its own failure modes. Kept as the follow-up if the measurement below
  shows uptime slots are not enough.
- Lowering VM memory, vCPUs or the Docker memory limits: hides the symptom, rejected by the
  operator.
- A wrapper script mounted through Swarm configs: more files and `CONFIG_VERSION` bumps for the
  same few lines; inline wrappers keep each service self-contained.

## Consequences

- After a VM start, a gated service may be unavailable for up to its slot (at most 660 s for
  comfy-gpu) even when the node is healthy; this is intended. Edit `STARTUP_GATE_SLOT_S` to tune
  a slot, or set it to `0` to disable the wait for one service.
- The slots assume dockerd and the node are Ready roughly 60-120 s after boot. Services whose
  slot has already passed when their task is assigned start immediately, which can bunch the
  earliest slots (whisper, ollama) if dockerd is late. Measure and adjust.
- Overriding `entrypoint` resets the image `CMD`; the services that relied on it now declare
  `command` explicitly (ollama `serve`, jellyseerr `pnpm start`). Image entrypoints were read
  from the registries (`/init`, `/bin/ollama`, `/sbin/tini --`, `tini -g --`, comfy
  `python -u main.py --listen --port 7860`, whisper `whisper-server`); a future image that
  changes its entrypoint must update the wrapper.
- Mid-recovery tasks keep restarting through the normal Swarm policy; nothing here restarts a
  daemon or a node.

## Verification

- `docker compose config` renders all five changed stacks (the repository's CI matrix), and
  `tests/test_gpu_node_staggered_start.py` asserts slot order and spacing, restart-delay order,
  the whisper start period and `vllm-gemma4` at zero replicas, and runs the gate with a fake
  uptime file and a fake `sleep` (waits only the remainder, passes arguments through, no wait
  after the slot).
- Deployment is one stack at a time through `cluster-utils`; each rollout is checked with
  `docker service ps` and the previous service spec is recorded for `docker service rollback`.
- Measurement at the next natural VM restart: per service, the container start time against the
  VM boot time (expect one service per slot); the peak of `vmmemWSL` and of Windows commit during
  the first 15 minutes against the 2026-11-10 baseline (12-24 GB, 7 panics between 12:17 and
  16:25 Chile); and whether any task exhausted `max_attempts`. Success is a lower panic rate over
  a stated window, not a quieter dashboard.
