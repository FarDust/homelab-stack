# Rust fixer rollout and dependent-service verification

Date: 2026-10-11 (UTC). This is the public, sanitized receipt; private infrastructure
identifiers and raw evidence remain in the operator's untracked canonical report.

## Delivered artifact and runtime

The reviewed Rust controller source was merged as `ba4aa57ee32b04eb2ed23b426e437563c4c4dd84`.
Its tree matches the independently tested PR head. The private registry artifact has digest
`sha256:31da1a2e04c24a960e93b16e0532dfd37d3baf76b763e30e65ce9f9fac343a1b`.
The registry-qualified reference is supplied privately through `RCLONE_CONTROLLER_IMAGE`,
not committed to this public repository. No new static key or IAM grant was introduced.

Canonical render, scoped `cluster-utils validate deployment` and single-service deploy
passed. The update completed at 06:23:49. Both Ready Linux/x86_64 nodes ran the exact
artifact with expanded local node bindings, read-only root/cache, all capabilities dropped,
64 MiB memory, 0.10 CPU, 32 PIDs and a separate persistent local journal. Samples were
13.12/16.82 MiB, two PIDs, zero restarts and no OOM. Down-node coverage is not claimed.

Initial configuration attempts used incorrect environment names and an argv node template;
they failed and were rolled back safely. The corrected contract uses
`RCLONE_EXPECTED_NODE_ID={{.Node.ID}}` and `RCLONE_ALLOWED_PLUGIN_REFERENCES` in the
environment, with command `--apply watch`. A transient replica count was not accepted as
completion: the actual image, environment and later cycles were checked.

The manager later completed driver-reachable cycles after an explicit inventory race.
The storage worker retained Docker API timeouts and cache-scan budget failures, reporting
unknown driver reachability rather than forcing unsafe recovery. The controller's stable
process does not establish healthy storage or recovered backups.

## Ollama read-only investigation

The low-end container started on 2026-10-10 at 16:35:54 and was still the same running
container with no OOM or restart. Neither Ollama service specification changed during the
fixer rollout. The primary service already had a pending task with no eligible node before
the rollout; no workload was moved to work around that condition.

Evidence from 2026-10-11:

| UTC | Observation |
|---|---|
| 05:05:09, 05:05:24, 05:05:39 | Low-end application logs already return 500 for `/api/tags`, before the production rollout attempts |
| 05:53:57 | `/api/version` returns 200 |
| 05:53:59 | `/api/tags` still returns 500 in the same container |
| 06:22:31 to 06:23:49 | Corrected fixer update starts and completes |
| 07:06:05 | Low-end loopback `/api/version` returns 200 in 0.01 s; `/api/tags` returns 500 in 0.22 s |
| 07:06:31 | The same `/api/tags` request from Traefik's network namespace returns 500 in 0.05 s |

The application error is `mkdir /root/.ollama: file exists: ensure path elements are
traversable`. A bounded read-only `stat` of that container path fails with `Transport
endpoint is not connected`; mount metadata confirms `fuse.rclone`. Traefik's configured
healthcheck is `/api/tags` (10 s interval, 2 s timeout), not `/api/version`.

The immediate mechanism is therefore a disconnected model-storage mount causing a real
500 on the healthcheck path. This is not merely a 2 s false-negative timeout: the failing
response was fast and reproducible from the proxy namespace. The underlying error
predates the Rust rollout; there is no evidence that this deployment created it. The
precise time Traefik marked the server down and the original cause of the mount disconnect
are not established. Full swap coexisted with the failure but is not proven its sole cause.

The earlier version-only 200 did not establish model-storage readiness. Final external
checks returned 503. Direct backend requests here were diagnostic controls, not substitute
acceptance of the user-facing route.

## Safe recovery proposal and remaining dependencies

Preserve the meaningful `/api/tags` healthcheck. Switching it to the shallow version
endpoint would conceal broken model storage. Do not recreate the stable low-end task
while the volume driver cannot reliably Get/Create its existing volume: that may convert
partial availability into a rejected task. First restore storage through the approved
capacity/plugin-maintenance procedure; then verify the existing healthcheck and Traefik
route. No such storage mutation, daemon/node restart, drain, new label or workload move
was performed during this investigation.

Keycloak and Authelia backups remain failed/preparing because of the storage-worker
driver failures. Their remediation depends on the operator's decision to allow the
existing `storage.manager == true` placement group, or to address capacity/storage in
place. The fixer rollout does not authorize that placement change.

Automatic private-registry auth refresh for future uncached nodes also remains separate;
the initial deployment used approved operator-mediated pulls. The full private rollback,
source hashes and raw task receipts remain available to the operator outside Git.
