# ADR: Standing disk retention policy for the CI/build worker

Date: 2026-11-13 10:20 UTC

## Context

The build worker (6 cores, 31 GiB RAM) runs CI jobs, game servers and Swarm services. Its root filesystem is an SSD logical volume that also holds the CI scratch, tool caches and `/tmp`; Docker data is on a separate volume. On 2026-11-13 09:23 UTC `/` was 93 % full with 5.8 GiB free, which stalls jobs and the Docker daemon's own writes. The owner's decision (2026-11-13): CI caches are not something to ask about; when they exceed a reasonable size they are pruned, as a standing rule.

Measured on 2026-11-13 (read-only first):

| Area | Size | Finding |
|---|---|---|
| `~/ci-agent-skills` | 3.3 GiB | 4,150 entries of CI job logs, Dockerfiles, review worktrees and archives; newest 7 days old, 3,929 entries older than 14 days |
| `~/.cache` (uv, pre-commit, Playwright, go-build) | 3.1 GiB | uv is hardlink-heavy: summing file sizes gives 8 GiB, real use 5 GiB |
| `~/.npm` | 1.2 GiB | `_cacache` 0.7 GiB, `_npx` 0.5 GiB |
| `/tmp` | at least 7.5 GiB (ten largest entries) | `node-compile-cache` 2.6 GiB written continuously, `tsx` cache, job leftovers |
| `~/ci-fallback` evidence | about 4 GiB | eight `dashboard-*` evidence directories (0.4-0.7 GiB each) last read at 02:12 UTC, so inside the 24 h window |
| `/dev/shm/agent-jobs` | 4.4 GiB | tmpfs (RAM): 12 directories of dead jobs, some with root-owned files from containers |
| Docker images | 88 GiB (33 GiB reclaimable) | on the Docker volume, not on `/` |

Two measurement pitfalls found while building the tool: following a symlink or listing a directory refreshes its atime, so a scan that counts them makes every path look in use; and the worker's own working directory sits at the parent of its scratch, so "a process holds a path that overlaps" must mean *inside* the candidate, not above it.

## Decision

Retention is a typed tool, `tools/node-retention` (uv, Python 3.13, pydantic-settings, Typer, Rich), with `plan` (dry run), `apply` and `guard` commands.

Thresholds (all `NODE_RETENTION_*` settings):

- `/` free space floor: 8 GiB. Tool caches (`~/.cache`, `~/.npm`, `/tmp` caches, CI uv/npm caches) stay under 6 GiB.
- Never touch anything read or written in the last 24 hours (`idle_hours`), or held open by a process (file descriptors and working directories under the candidate), or bind-mounted into a container (a mount source at or below the candidate).
- CI evidence (`dashboard-*`, `*-evidence`, `*.bundle`, `er-release-*`, `jra/*evidence*`): removed after 14 days. CI scratch roots (`~/ci-agent-skills`): children removed after 14 days. CI git-archive tarballs: 7 days. `/tmp` entries owned by the CI user: 7 days idle.
- `/dev/shm/agent-jobs`: a directory named `<UTC stamp>-<pid>` goes once the pid is dead and one hour has passed since its last use; other job directories after 24 h idle.
- Tool caches are pruned only when over the 6 GiB budget or when `/` is under its floor. Independent content-addressed caches (`/tmp/node-compile-cache`, tsx, npm `_cacache`, go-build) are pruned file by file, for singly linked files not read or written in 24 h; whole-directory caches (uv, pre-commit, Playwright, `_npx`) are pruned oldest first as units, never a unit used in the last 24 h.
- Docker: dangling images (no container references them) and build cache older than 7 days through Docker's own prune commands. Volumes are never pruned by this tool.
- Protected without exception: `journey-rollback`, `jt-dumps`, the job ledger, Pterodactyl data, Olympus staging, the CI queue's `queue-archives`, everything the policy does not name. Unidentified paths are never candidates.

Mechanics:

- `apply` writes the manifest (path, size, age, reason, category) to the state directory **before** the first deletion, re-checks recency, open files and mounts immediately before each delete, verifies the path is gone afterwards, and falls back to a one-shot helper container for root-owned leftovers (job containers create them), verifying again. Each entry ends `deleted`, `skipped-*` or `failed`.
- A ledger row `who=retention` (start and end, with freed bytes, free space before and after and the manifest path) goes to `~/ci-fallback/ledger.jsonl`. The ledger informs; it is not a lock.
- Metrics go to the node_exporter textfile collector (`node_retention_root_free_bytes`, `..._floor_bytes`, `..._last_check_timestamp_seconds`, `..._last_run_*`). The collector directory is root-owned, so the publisher writes through the same helper-container route other node jobs use.
- Two systemd user timers: `node-retention-guard` every 10 minutes (publishes the metric and runs `apply` when `/` is under the floor) and `node-retention-apply` every 6 hours. Alerts: `NodeRootFreeBelowRetentionFloor` (under the floor for an hour although the guard prunes), `NodeRetentionStale` (no check for an hour), `NodeRetentionRunFailed`.

## First run, 2026-11-13

Free space on `/`: 4.9 GiB before, 9.0 GiB after (the floor is met). Freed per category as the manifest records it: CI scratch 5.65 GiB (3,917 entries; shared hardlinks inflate the sum, the net gain on `/` was about 4.1 GiB), tool-cache stale files 0.83 GiB, whole tool caches 0.82 GiB, tarballs 0.08 GiB, `/tmp` leftovers 0.05 GiB, Docker dangling images 2.05 GiB (Docker volume, not `/`). Evidence directories freed nothing yet: the eight large ones were read at 02:12 UTC and become eligible after the 24 h window. Twelve dead `/dev/shm` job directories and twelve CI scratch entries failed on root-owned files; the helper-container fallback was added and the cleanup rerun.

## Dangling Docker volumes (numbers and a proposed rule; nothing deleted)

At 09:30 UTC Docker listed 1,816 volumes with no container (156 GB). Sizes through `docker system df -v`, contents sampled read-only through a helper container mounting the volume directory read-only:

- 1,726 are anonymous (64-hex names): 34.5 GB. 73 of them hold more than 100 MB (22.7 GB). All 80 sampled non-empty ones are PostgreSQL data directories (`PG_VERSION`, `base`, `global`: 23.1 GB, up to 0.8 GB each), from throwaway test databases of removed job containers; 17 sampled ones were empty. None looks like node_modules or an npm cache.
- 80 are named: 118.8 GB. They are not regenerable scratch: Rust `target` caches (32.5, 11.2 and 10.9 GB), a Netdata metadata backup (11.6 GB), RAGFlow data (9.7 GB), the Minecraft Advanced Backups history (9.0 GB), a mod-purge pilot, Loki data, whisper models and Android and Flutter toolchains.

Proposed rule, for a separate decision because a volume can hold data: never prune named volumes; prune an anonymous volume only when it is unreferenced by any container, running or stopped, is at least 7 days old, and is either empty or a PostgreSQL data directory whose only databases are the template ones or which no service of the stack uses; write the manifest with the inventory first. The empty anonymous volumes (about half by count, no bytes) are safe under any rule and a first batch.

## Alternatives

- **`docker system prune` or `docker volume prune`.** Rejected: prunes named volumes of scaled-to-zero services and removes rollback images.
- **`tmpreaper` or a `find -atime` cron.** Rejected: no manifest, no open-file or mount check, no ledger or metric, and hardlinked caches are miscounted.
- **A lock to keep jobs away while pruning.** Rejected by the owner's rule: agents run in parallel, and the idle window plus the open-file check give the same protection without queueing.
- **Counting directory and symlink atime as use.** Rejected: the scan itself refreshes them.

## Consequences

- The policy cannot free more than the identified, aged categories hold. If `/` stays under the floor, the alert fires and the manifest names what is left; the next lever is moving job scratch to tmpfs or another volume, not a lower floor.
- A cache used continuously by a running job is never removed whole, so budget pressure is relieved file by file first.
- Evidence removal after 14 days does not check that the PR is merged (the node has no GitHub credentials); evidence posted on the PR is the durable copy.

## Verification

- 25 unit tests with in-memory ports, plus filesystem tests on Linux: thresholds, the 24 h and 14 day gates, open-file, parent-directory and mount handling, protected paths, manifest-before-delete ordering, root-helper fallback and a failed helper, the ledger row and the metric text.
- First `plan` reviewed against the protected set before `apply`; `df -h /` before and after recorded above.
- `promtool test rules` covers the three retention alerts.
