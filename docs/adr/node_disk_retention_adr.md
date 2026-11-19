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
- `/dev/shm/agent-jobs` (RAM): a directory named `<UTC stamp>-<pid>` goes once the pid is dead and one hour has passed since its last use; every other tree follows the four rules of the section "Tmpfs job trees" below (supersedes the former single 24 h rule).
- Tool caches are pruned only when over the 6 GiB budget or when `/` is under its floor. Independent content-addressed caches (`/tmp/node-compile-cache`, tsx, npm `_cacache`, go-build) are pruned file by file, for singly linked files not read or written in 24 h; whole-directory caches (uv, pre-commit, Playwright, `_npx`) are pruned oldest first as units, never a unit used in the last 24 h.
- Docker: dangling images (no container references them) and build cache older than 7 days through Docker's own prune commands. Volumes are never pruned by this tool.
- Running jobs: every job of the node ledger (`~/ci-fallback/ledger.jsonl`) whose last row is not `end` or `refused` and whose pid is alive or unknown protects the paths it names (`where_fs`, `where`, `workdir`), both the tree that contains them and the tree below them. A job path at or above a deletion root (`/tmp`, the home directory) names an area rather than scratch and protects nothing by itself. The ledger is read, never locked.
- Fail closed: a missing or unreadable ledger, or a malformed row (other than a final row still being appended or an old row, see "Tmpfs job trees"), stops the plan before any candidate exists; during `apply` it fails each remaining entry. The run is reported as failed in the metrics.
- Path safety: a candidate lies strictly below a configured root (or is a configured cache unit), contains no `..`, and no ancestor is a symlink (`realpath` of the parent equals the parent); a file-by-file cache unit must not be a symlink itself. A tree that holds a mount point (`/proc/self/mountinfo`) or a Unix socket (tmux, ssh-agent, .NET diagnostics: their holders are invisible in `/proc/<pid>/fd`) is never removed. Roots under `/bin`, `/boot`, `/etc`, `/lib`, `/proc`, `/run`, `/sbin`, `/sys`, `/usr`, `/var/lib`, `/dev` (other than `/dev/shm`) or `/` itself are rejected at configuration time.
- Protected images: `protected_image_refs` maps an image reference to its expected id (generic and empty by default; the node's private settings supply the real mapping, for example a CI cleanup helper that the recorder end-to-end runner starts with `--pull=never`, where a pruned image makes every cleanup fail and leaks root-owned scratch). `plan` and `apply` verify every reference before any image prune, and `apply` verifies again just before the prune. A reference that is missing or resolves to another id refuses the image prune, prints the reference, expected id and observed id, ends `plan` and `apply` with exit 1, and records the run as failed (manifest `protected_image_violations`, ledger `exit=1`, run metric). A lookup that fails for any other reason (daemon error, empty or malformed answer) raises `ImageLookupError` and aborts the run in `plan`, at the start of `apply` and in the per-entry recheck alike: the run ends failed (ledger `exit=1`, run metric) and the error reaches the caller, since an unknown image state is never read as intact. A docker timeout or a missing binary counts as a lookup failure too. The `start` ledger row is written before the first check, so an abort always leaves a `start` and a failed `end` row. An expected id must match `sha256:<64 hex>` (validated when the settings load), and an empty observed id is an error, so an empty answer can never equal an expected id. `verify-images` is the same check as a command so that any other image-pruning script on the node can gate on it. The Docker adapter refuses every argument list that contains `prune` (image, builder, system, container, volume or network) together with `--all` or `--volumes` (with or without `=value`) or any short-flag cluster containing `a` (`-a`, `-af`, `-fa`, `-a=true`); only dangling images and aged build cache are pruned. The legacy node script `docker-safe-prune.sh` (`image prune --filter until=24h`, no `-a`) is not part of this repository: it must call `verify-images` before pruning and must never gain `-a`. Tests: `tools/node-retention/tests/test_protected_images.py`.
- Checked exception, `stacks/main/maintenance.yml`: its scheduled job runs `docker system prune -f --filter until=72h` and `docker builder prune -af`. Neither can remove a tagged protected image: `system prune` without `-a` removes only dangling images, and `builder prune -a` removes build cache, not images. The stack does not call `verify-images`, so a drifted protected image is not reported there; wiring that call is tracked in a follow-up issue. Adding `-a` to the system prune, or `docker image prune -a`, would break the protection and needs the guard first.
- Protected without exception: `journey-rollback`, `jt-dumps`, the job ledger, Pterodactyl data, Olympus staging, the CI queue's `queue-archives`, everything the policy does not name. Unidentified paths are never candidates.

Mechanics:

- `apply` writes the manifest (path, size, age, reason, category) to the state directory **before** the first deletion, re-checks path safety (re-reading the ledger), recency, sockets, open files (descriptors, cwd, executable and memory-mapped files) and container mounts immediately before each delete, verifies the path is gone afterwards, and falls back to a one-shot helper container for root-owned leftovers (job containers create them), verifying again. Each entry ends `deleted`, `skipped-*` or `failed`.
- A ledger row `who=retention` (start and end, with freed bytes, free space before and after and the manifest path) goes to `~/ci-fallback/ledger.jsonl`. The ledger informs; it is not a lock.
- Metrics go to the node_exporter textfile collector in two files: `node_retention.prom` (`node_retention_root_free_bytes`, `..._floor_bytes`, `..._last_check_timestamp_seconds`), rewritten by every guard and apply, and `node_retention_run.prom` (`..._last_run_*`, `..._last_planned_bytes`), written only by a prune run, including one that aborts. Keeping them apart stops the 10-minute guard from erasing the result of the last prune, which made `NodeRetentionRunFailed` unable to stay firing. The collector directory is root-owned, so the publisher writes through the same helper-container route other node jobs use.
- Two systemd user timers: `node-retention-guard` every 10 minutes (publishes the metric and runs `apply` when `/` is under the floor) and `node-retention-apply` every 6 hours. Alerts: `NodeRootFreeBelowRetentionFloor` (under the floor for an hour although the guard prunes), `NodeRetentionStale` (no check for an hour), `NodeRetentionRunFailed`.

## First run, 2026-11-13

Free space on `/`: 4.9 GiB before, 9.0 GiB after (the floor is met). Freed per category as the manifest records it: CI scratch 5.65 GiB (3,917 entries; shared hardlinks inflate the sum, the net gain on `/` was about 4.1 GiB), tool-cache stale files 0.83 GiB, whole tool caches 0.82 GiB, tarballs 0.08 GiB, `/tmp` leftovers 0.05 GiB, Docker dangling images 2.05 GiB (Docker volume, not `/`). Evidence directories freed nothing yet: the eight large ones were read at 02:12 UTC and become eligible after the 24 h window. Twelve dead `/dev/shm` job directories and twelve CI scratch entries failed on root-owned files; the helper-container fallback was added and the cleanup rerun.

## Dangling Docker volumes (numbers and a proposed rule; nothing deleted)

At 09:30 UTC Docker listed 1,816 volumes with no container (156 GB). Sizes through `docker system df -v`, contents sampled read-only through a helper container mounting the volume directory read-only:

- 1,726 are anonymous (64-hex names): 34.5 GB. 73 of them hold more than 100 MB (22.7 GB). All 80 sampled non-empty ones are PostgreSQL data directories (`PG_VERSION`, `base`, `global`: 23.1 GB, up to 0.8 GB each), from throwaway test databases of removed job containers; 17 sampled ones were empty. None looks like node_modules or an npm cache.
- 80 are named: 118.8 GB. They are not regenerable scratch: Rust `target` caches (32.5, 11.2 and 10.9 GB), a Netdata metadata backup (11.6 GB), RAGFlow data (9.7 GB), the Minecraft Advanced Backups history (9.0 GB), a mod-purge pilot, Loki data, whisper models and Android and Flutter toolchains.

Proposed rule, for a separate decision because a volume can hold data: never prune named volumes; prune an anonymous volume only when it is unreferenced by any container, running or stopped, is at least 7 days old, and is either empty or a PostgreSQL data directory whose only databases are the template ones or which no service of the stack uses; write the manifest with the inventory first. The empty anonymous volumes (about half by count, no bytes) are safe under any rule and a first batch.

## Independent review, 2026-11-13 (tool 0.2.0)

The first version (0.1.0) was reviewed as dangerous code after its first run. It did not read the job ledger at all, so a running job whose scratch had not been written for the idle window (for example `/tmp/jt-*` trees, or `/dev/shm/agent-jobs/<who>-<name>` directories whose names carry no pid) was protected only by the idle and open-file checks; it followed a symlinked root or ancestor; `rmtree` and the root helper would cross a mount point inside a candidate; trees holding a live Unix socket were removable (a `.NET` diagnostic socket of a running process sat in `/tmp`, two days from the 7-day gate); memory-mapped and executable files were not counted as open; and the guard overwrote the run metrics every 10 minutes. The dry run on the node at review time proposed only the `/tmp/node-compile-cache` stale files and Docker's dangling images and build cache, nothing protected, so the apply timer stayed enabled while 0.2.0 was prepared. Each case has a regression test in `tools/node-retention/tests/test_safety.py`.

## Alternatives

- **`docker system prune` or `docker volume prune`.** Rejected: prunes named volumes of scaled-to-zero services and removes rollback images.
- **Rely on today's flags alone (`image prune` without `-a` keeps tagged images).** Rejected: nothing would stop a later `-a`, a retag that leaves the id dangling or a manual `docker rmi`; the guard compares the id, so drift is a failure instead of a silent later outage.
- **`tmpreaper` or a `find -atime` cron.** Rejected: no manifest, no open-file or mount check, no ledger or metric, and hardlinked caches are miscounted.
- **A lock to keep jobs away while pruning.** Rejected by the owner's rule: agents run in parallel, and the idle window plus the open-file check give the same protection without queueing.
- **Counting directory and symlink atime as use.** Rejected: the scan itself refreshes them.

## Consequences

- The policy cannot free more than the identified, aged categories hold. If `/` stays under the floor, the alert fires and the manifest names what is left; the next lever is moving job scratch to tmpfs or another volume, not a lower floor.
- A cache used continuously by a running job is never removed whole, so budget pressure is relieved file by file first.
- Evidence removal after 14 days does not check that the PR is merged (the node has no GitHub credentials); evidence posted on the PR is the durable copy.

## Verification

- Unit tests with in-memory ports (`tests/test_policy.py`, `tests/test_safety.py`: unreadable ledger before and during a run, running-job paths in both directions, a job that starts after the plan, symlinked roots and units, mount points, sockets, a file read mid-run, forbidden roots, an aborted run's metric), plus filesystem tests on Linux (real sockets, mountinfo parsing, `realpath`, the JSONL ledger's fail-closed parsing): thresholds, the 24 h and 14 day gates, open-file, parent-directory and mount handling, protected paths, manifest-before-delete ordering, root-helper fallback and a failed helper, the ledger row and the metric text.
- First `plan` reviewed against the protected set before `apply`; `df -h /` before and after recorded above.
- `promtool test rules` covers the three retention alerts.

## Tmpfs job trees (2026-11-19, owner lira, review 2026-11-26)

### Context

On 2026-11-18 21:10 UTC `/dev/shm/agent-jobs` held 10.7 GB and swap free fell to 0.68 GB with no swapping, although the CI gate has an end hook that collects trees. The hook (`lanes_gc_hook` in `gate-lib.sh`) only removes superseded head trees of the lane of the job that ends, so trees of lanes that finish stay in RAM for good: about 5.2 GB were idle trees of finished lanes (`fix179`, `gpx173-*`, `jra-rel0570`), some five days old. A manual cleanup freed 6 GB; it was a workaround. The standing collector that should have caught the rest, `node-retention apply` every six hours, had been failing since 2026-11-13 12:21 UTC: three rows of the job ledger written by the former Bash writer (`"tree_mb":,`, a `du` failure) are not JSON, and the fail-closed rule stopped every plan. Root disk, caches and tmpfs retention were all down for five days.

### Decision

Two changes, both in this tool (the gate has no repository of its own and calls the tool):

1. Rules for every tree below `shm_jobs_root`, evaluated by `application/shm_trees.py`; a tree that a process holds (descriptor, cwd, mapped file), that a container mounts, that a running ledger job names, or that holds a socket is never a candidate, as for every other category:
   - pid-named directories: removed one hour after the pid died (unchanged);
   - any tree untouched for `shm_idle_hours` (24 h): removed whatever its lane does;
   - any tree untouched for `shm_idle_minutes` (120 min): removed when its lane (longest ledger `who` that prefixes the tree name) has no job running or deferred; a tree no ledger lane owns is kept like an active lane until the 24 h ceiling; a job counts while the last row of its id is not `end`/`refused` and its pid is alive; note rows never end a job;
   - cap: when the directory exceeds `shm_cap_gib` (8 GiB) after those removals, the oldest trees idle for at least `shm_cap_min_idle_minutes` (10 min) go first until it fits, trees whose lane has no running job before trees of active or unknown lanes.
2. Ledger tolerance: a malformed row is skipped when its own `ts` is older than `ledger_malformed_tolerance_hours` (48 h), because an old row cannot describe a running job; the run prints the skipped line numbers. A recent row, or one without a readable `ts`, still fails closed. The ledger file is append-only and is not edited.

Entry points: `node-retention shm-gc [--dry-run] [--json]` plans and applies only the tmpfs rules; the gate's end hook runs it after every job (detached, bounded), and `node-retention guard` runs it on every 10-minute timer tick (no new timer: the existing guard unit covers it). `apply` includes the same rules in its six-hourly run. Every run that removes trees writes the manifest to the state directory before deleting and one ledger note row (`kind: tree-gc`, `gc_removed` with tree, MB, age and reason, `manifest`) so lanes read what disappeared and why. Thresholds are `NODE_RETENTION_SHM_*` settings (`deploy/node-retention.env.example`).

### Alternatives

- Extend the gate hook in Bash to scan all lanes: rejected; the tool already owns the process, mount and ledger checks, has tests and a manifest, and the language policy keeps new logic out of Bash.
- A lock or serial queue around tree removal: rejected by the standing rule; the ledger and measured use decide, nothing blocks another process.
- Drop fail-closed for the ledger: rejected; only rows too old to matter are tolerated.
- A separate timer for tmpfs: unnecessary; the guard already runs every 10 minutes and fails the unit when tmpfs collection fails.

### Consequences

A tree of a lane that runs continuously survives until 24 h idle unless the cap needs it, so an active lane keeps its current trees; a finished lane releases its RAM within two hours and a ten-minute tick. The collector costs one directory walk of the tmpfs trees per tick (idle I/O class, tmpfs). A long job whose tree is idle for ten minutes and whose lane is running can be evicted by the cap only when the directory is over 8 GiB and the job is not named in the ledger or holding the tree open; rollback is to raise `NODE_RETENTION_SHM_CAP_GIB` or revert the version.

### Verification

`tests/test_shm_trees.py` covers each rule, the in-use guards, the cap order, the fail-closed ledger, the ledger note and the dry run; live proof on frost-fang is recorded in `Learnings/frost-fang gate tree collector for finished lanes 2026-11-19.md` of the agent memory vault.

## uv cached environments (2026-11-19, owner lira, review 2026-11-26)

### Context

On 2026-11-19 00:16 UTC frost-fang `/` (vg0-root, 79 GB) had 4.7 GB free against the 8 GiB floor. The guard ran and reported nothing on `/` left to prune: the two uv caches (`~/ci-fallback/uv-cache` 8.6 GB, `~/.cache/uv` 4.0 GB) are cache units judged as a whole, and both are written every hour, so they never pass the 24 h gate. Measured inside them: `environments-v2` held 6.1 GB and 1.2 GB of cached ephemeral environments (109 and 27 entries, created by `uv run --script`, `--with` and `uvx`), while `archive-v0` held 2.4 and 2.8 GB. Four uv versions (0.7.13 on the host, 0.11.7, 0.12.5 and 0.13.7 from jobs) write the same cache.

### Decision

List each cache's `environments-v2` directory in `cache_roots`, so every environment is its own least-recently-used tool cache under the existing rules: pruned only when the floor or the budget needs it, only after 24 h without a write or read, never while a process holds it. The planner counts a unit nested in another unit once (the budget is not inflated by the environments inside their cache) and never chooses both a unit and a unit nested in it: the environments, being older, go first and the cache that holds `archive-v0` is skipped with the reason `nested with a cache unit already chosen`.

### Alternatives

- `uv cache prune`: it removes every cache bucket the running uv version does not know, including the newer buckets of other versions on the same cache (`simple-v27`, `wheels-v7`), and the archives only they reference; with four writer versions that forces heavy re-downloads. Kept for a single-version cache.
- Delete the whole cache when the floor is violated: discards `archive-v0`, which is the expensive part.

### Consequences

Removing an environment costs the next `uv run` of that script a rebuild from `archive-v0` (links or copies, no download). Environments in use within 24 h stay. The version drift that multiplies buckets is a separate finding for the gate owner.

### Verification

`tests/test_policy.py::test_idle_uv_environments_inside_an_active_cache_are_pruned_one_by_one` and `::test_idle_cache_and_its_nested_environments_are_not_both_candidates`; live numbers in `Learnings/frost-fang root disk 94 percent 2026-11-19 uv environments and rclone cache.md` of the agent memory vault.
