# ADR: Bound read-only job reporting inside the original job deadline

Status: implemented candidate; rollout requires the verification and adoption gates below.

## Context

Two fallback-job observations separated payload completion from process completion:
17.942 seconds of payload followed by 234 seconds after its END row, and 27.811
seconds followed by approximately 148 seconds. Those are measured lifecycle
intervals, **not proof that a particular hook caused them**. The footer invokes
the container reaper and retention hooks sequentially. Inspection establishes
that the old stale-tree reporter is unbounded: for each old tree it starts a new
process-table scan, including one external `readlink` per process, and repeats
ledger and directory walks. The number of trees multiplies the process-table cost.

The established retention package already owns the filesystem/process/container
boundaries. Reporting belongs there rather than in a second shell implementation,
an admission override, another ledger store, or a larger CI timeout.

## Decision

1. `node-retention` 0.4.0 adds `node-retention-report`, implemented in
   `node_retention.reporting/{domain,application,adapters}` with an explicit
   composition root and thin Typer CLI. Domain/application ports receive clock,
   inventory, process, container, ledger and publisher implementations. There is
   **no deletion port**. The existing plan/apply/guard policy is unchanged.
2. Acquire one process snapshot with psutil, build an ancestor-path index once,
   and acquire running-container metadata in one batch. Every tree checks the
   index instead of rescanning processes. The snapshot covers a time interval,
   not an atomic lease or permission to delete anything later.
3. Preserve marker-owner / longest-known-prefix owner selection, the six-hour
   default and configured age, top-two-level idle semantics, live-tree and mount
   protection, historical-note deduplication, and the gate-name rule for
   unlabelled old containers. Reports never remove trees or containers.
4. Missing process permissions, changed/unreadable trees, failed Docker queries,
   malformed required metadata and missing original-deadline evidence remain
   explicit unknown/partial results. Unrelated malformed historical ledger rows
   stay untouched and make coverage partial. A complete result is not fabricated
   from an empty or failed observation. Malformed own-job evidence denies use of
   an earlier matching START rather than silently accepting a stale deadline. Independently verified old-container
   reports can still be published when tree process coverage is unknown.
   Active ledger paths and ancestor mounts protect trees. Findings capture the
   observed device/inode and terminal job references; these are bounded snapshot
   facts, never proof of future non-use or authorization to delete. Every finding
   explicitly carries `retention_authorized=false`.
   Tree identity is checked before and after measurement. Complete absolute argv
   values, including spaces, retain their observed and conservative lexical path
   spellings. Structured report names are authoritative; only legacy rows without
   that field use bracket-text deduplication. Invalid structured names and external
   container identities remain explicit incomplete evidence.
5. Before publishing START, the legacy entry point captures the admission epoch
   and expected duration. Typed settings require both; the reporter checks the
   resulting deadline against the persisted aware START timestamp and duration.
   When invoked through the host wrapper, the report worker and imports get at
   most four seconds, with up to one second for the native outer termination
   grace and a two-second original-budget cushion. No report receives a later
   deadline than the original job. No fresh timeout is granted after bootstrap,
   END or worker creation. Direct CLI invocation has no outer import/configuration
   timeout; its worker budget begins after those steps. Canonical adoption uses
   the host wrapper.
6. A supervisor owns a fresh process group for blocking observations. Its outer
   timeout includes worker startup, observations and publication, with a small
   cleanup reserve. On exhaustion it terminates only that owned group and returns
   unknown; unverifiable termination is reported as such. Cancellation is deferred
   across handle creation and cleanup, then propagated, with handlers restored.
   The preinstalled util-linux `setpriv --pdeathsig KILL` wrapper protects the
   worker if its original controller dies; an internal parent-PID handshake
   precedes application imports. It changes no UID, GID or capability. Existing
   GNU timeout bounds the outer CLI and each external observation/publication.
   External-command watchdogs retain their own process groups and survive worker
   death to kill descendants at the unchanged report deadline. A verified worker
   exit alone does not assert that every descendant has already exited.
   [Native parent-death interface](https://man7.org/linux/man-pages/man1/setpriv.1.html).
7. Reuse the configured existing ledger-publisher executable and its validated
   atomic append contract. Notes are bounded chunks of at most two findings;
   the current flow publishes each verified finding before starting another
   observation, so a later blocked read cannot discard prior ledger progress.
   Independently verifiable containers are published before tree traversal.
   serialization uses JSON. No direct writer or parallel durable state is added.
   The reporter emits a typed outcome even when it publishes no note. The shim
   routes it to the existing job diagnostic stream instead of hiding failures.
8. Retire the overlapping shell reporting bodies via the canonical host-config
   patch. The two compatible function names dispatch the same per-job report
   once. This is process-local idempotency, not an agent lock or queue. Admission
   thresholds, the host budget, owner-tree removal, job sweeping and the container
   reaper remain unchanged. Optional maintenance failure does not replace the
   payload exit code; its separate nonzero/partial report stays visible.

## Libraries and implementation boundary

- psutil 7.2.2 owns process enumeration/cache and `oneshot()` collection. Its
  upstream repository had **11,322 stars (threshold: 1,000)** at the 2026-11-15
  metadata check; provider is the psutil maintainers, licence BSD-3-Clause.
  Version is constrained below 8 so the selected API is deliberate.
  [Official API](https://psutil.readthedocs.io/stable/).
- Python's standard library owns filesystem observations, subprocess lifecycle,
  signals and JSON. Custom code is the existing owner/idle/dedup reporting policy
  and its budget/uncertainty integration, not a replacement process framework.
- Existing Pydantic, pydantic-settings, Typer and Rich own schemas, configuration,
  CLI and diagnostic rendering. Standard `os.scandir` integration retains the
  top-two-level age rule while counting allocated bytes and checking mount and
  hardlink boundaries under the shared budget.
- uv owns the locked environment and build. Cache keys include `pyproject.toml`
  and `src/**/*.py` because local-directory defaults do not track every source
  edit. [Official cache semantics](https://docs.astral.sh/uv/concepts/cache/).

## Alternatives

- Disable the GC hook or increase the CI deadline: rejected; neither repairs the
  repeated scan or preserves honest job timing.
- Cache a process list in mutable shared shell state: rejected; it adds another
  stale-state mechanism and still leaves blocking observations unbounded.
- Rewrite admission and destructive retention at the same time: deferred as a
  separate migration. This change ports the complete read-only reporting boundary.
  The unchanged legacy admission/removal implementation is an explicit temporary
  compatibility exception protecting active jobs and retention safety; it is not
  claimed to be a finished whole-helper port.
- Keep the old reporter beside the new one: rejected. The compatibility functions
  delegate to the package, including the old-container report, with one invocation.

## Consequences and limits

An unprivileged process snapshot may legitimately be incomplete. The outcome then
says unknown/partial instead of asserting that another user's tree is unused.
Reporting all very large inventories may take multiple bounded runs; previously
published names remain deduplicated in the existing bounded ledger window.

This change bounds the **report phase**, not every legacy footer operation. A slow
container reaper or owner-tree removal must retain its own failure attribution.
The observed 234/148-second tails do not identify which hook ran. The regression
fixture isolates the confirmed unbounded reporter path without running deletion.

The host-config patch is reviewed data, not a new large shell tool. Its synthetic
historical fixture preserves relevant code and line structure while replacing
deployment identifiers. Actual preimage bytes, digest, installed mappings and
runtime receipts remain private operator evidence. Production is installed from
a wheel into an immutable version/digest directory. The profile is captured when
the helper is sourced; atomic promotion affects future jobs, not imports beneath
an already admitted job.

## Verification and rollout

- Behavioral tests cover owner/idle/live/mount/dedup rules, 10,000 trees with one
  process and container snapshot, malformed required fields, downstream failure,
  missing-data denial, nondisclosure, cancellation and unknown termination.
- The native package gate exposed an existing fixture assumption: an absolute
  AF_UNIX bind address exceeded the kernel limit under an admitted job path. The
  fixture now binds relative to its owned directory, restores the caller cwd, and
  exercises both ordinary and deliberately long directory names; socket, mount
  and symlink assertions remain unchanged. No special short runtime path or
  production socket policy is substituted.
- Native Linux tests exercise real filesystem/mount observations and an isolated
  no-delete historical-versus-package lifecycle measurement. A hard original
  deadline, not the current host's quietness, is the assertion.
- Patch tests prove admission thresholds and the destructive owner/removal/reaper
  functions are unchanged. Source/test modules and the legacy fixture stay below
  the 1,000-line ceiling.
- Independent source review, locked tests, wheel-installed CLI/import checks,
  native no-delete lifecycle evidence and exact source/runtime hashes precede
  canonical adoption. Source tests alone do not establish deployment.
- Follow the [host-config adoption/rollback guide](../../host-config/ci-job-reporting/README.md).
  Retention activation, data deletion, restarts and host-budget changes are not
  part of this reporting rollout.
