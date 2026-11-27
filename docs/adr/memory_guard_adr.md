# Memory guard for the Windows desktop

Status: accepted, 2026-11-25. Implementation: `tools/memory-guard` (0.2.0). Addendum 2026-11-25: opt-in WSL cache drop.

## Context

On 2026-11-25 the owner's Windows desktop (32 GB RAM, about 78 GB commit limit) ran at 68.3 GB commit with 0.79 GB free
RAM for roughly 45 minutes, and Claude Code stopped several agent lanes' background waits for low memory. Nothing
alerted. A non-paged pool leak of about 9 GB, growing about 0.34 GB per day, and the WSL VM page cache held as
host commit were the contributors. The desktop comes first, so the watchdog must cost almost nothing.

## Decision

- A small uv package, `memory-guard` (`domain`, `application`, `adapters`, `cli`, composition root), run by a
  Windows Task Scheduler task every 5 minutes, hidden through `conhost --headless`, priority BelowNormal.
- Readings: `GetPerformanceInfo` (ctypes, one call) for commit total, commit limit and the non-paged pool, because
  psutil exposes none of those; psutil for available RAM and each process's private bytes. A missing or zero reading
  raises `ProbeError`.
- Rule: free virtual (limit minus commit) under 8 GiB or free RAM under 1 GiB in two consecutive samples. The
  counters live in a small JSON state file under the state directory. One alert per condition per 30 minutes; a
  recovery message when a previously alerted condition is clear again.
- Alert text carries commit and limit, free RAM, the non-paged pool and the top 10 processes by private bytes.
- Alert path: an external command from `MEMORY_GUARD_ALERT_COMMAND` (arguments separated by `|`, with a `{message}`
  placeholder), the agent-bridge helper's `post`. Success needs exit 0 and the `delivered` receipt in stdout; a
  failure exits 1 with the cause on stderr, does not mark the condition as alerted; the attempt counts toward the rate limit, so the retry comes after one interval (0.1.1).
- Never signals, kills or modifies a process, and starts neither WSL nor anything heavy. Since 0.2.0 it is no longer strictly read-only: see the addendum for the one opt-in remediation.
- Uninstall: `Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false`.

## Alternatives

- Perfmon data collector or a Windows event trigger: no alert path to the agents, and a counter set to maintain.
- Reading the pool through `Win32_PerfRawData` (CIM/WMI): heavier per run than one `GetPerformanceInfo` call.
- A Netdata or Grafana alert: the desktop pool and commit are not in the cluster metrics, and the incident was
  specific to this host.
- Killing the top process automatically: rejected, it could destroy Gabriel's work.

## Libraries

- psutil: more than 1,000 GitHub stars (about 11 k), BSD-3-Clause, widely used. Only the ctypes call for
  `GetPerformanceInfo` is custom, because no maintained binding in the standard stack exposes the kernel pool.
- pydantic-settings, Typer, Rich: the standing stack.

## Consequences

- One short process every 5 minutes (about 100 ms CPU); no resident memory between runs.
- Two samples mean an alert after 5 to 10 minutes of sustained pressure; a spike shorter than that is ignored.
- Delivery is at least once: an alert whose state save fails is sent again on the next run. A recovered condition keeps its last alert time, so a flap stays inside the 30-minute limit.
- The alert path depends on the agent-bridge helper and its recipient; its failure is visible as a failed task run.

## Verification

- Tests through the public API (`tools/memory-guard/tests`): single sample, two samples, rate limit, recovery,
  independence of the RAM condition, alert failure and retry, probe failure, malformed state, CLI exit codes.
- After merge: the task registered from the merged tree, two runs with exit 0, and a forced-threshold run
  (`check --min-free-virtual-gb 100000 --state-dir <temp>`) that proves the alert path.

## Addendum 2026-11-25: opt-in WSL page-cache drop (0.2.0)

### Context

The desktop kept hitting commit pressure (free virtual memory 3 to 5 GB of 78 GB) because the WSL2 VM process
`vmmemWSL` held 20 to 24 GB of committed memory while the guest used about 6.5 GB. Dropping the guest page cache freed
about 4.4 GB each time and it refilled in about 20 minutes. Measured twice on 2026-11-25 (17:27Z and 17:49Z): free
virtual 4.9 to 10.0 GB and 6.0 to 9.2 GB, `vmmemWSL` 24.5 to 20.1 GB and 24.3 to 19.9 GB, with
`sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory` run as root in the already running
distro. The owner approved the WSL cache drop as a mitigation and keeps `.wslconfig` and `wsl.conf` unchanged.

### Decision

- `memory-guard check` runs the drop itself when all hold: free virtual memory below the threshold in
  `MEMORY_GUARD_RECLAIM_SAMPLES` (2) consecutive samples; the distro (`MEMORY_GUARD_WSL_DISTRO`, `Ubuntu`) is already
  listed by `wsl --list --running` (a stopped distro is never started); the last attempt is over 10 minutes old; fewer
  than 6 attempts in the last hour (an attempt that reached the drop counts, failed or not; a failure before it, such as a missing `vmmemWSL` counter, raises on each run until fixed). The drop is `wsl.exe -d <distro> -u root -- sh -c ...`
  in a subprocess with a 60 s timeout.
- Free virtual, free RAM and `vmmemWSL` private bytes are read before and after (the after reading polls the counters
  for up to 20 s until `vmmemWSL` shrank by 1 GiB: a bound, not a fixed wait). Both go into the alert or recovery
  message and one line of `<state-dir>/reclaim.jsonl` (trimmed to 500 lines past 1000).
- The drop runs before the alert is posted, so a slow alert path (the agent-bridge post) never delays it.
- Failure is explicit: `wsl.exe` missing, a nonzero exit, a timeout, a missing `vmmemWSL` counter or an unreadable log
  exit 1 with the cause and a recovery hint on stderr; when the alert is due (30-minute limit) it carries the failure. Compaction is best-effort (`|| true`) because kernels without it would otherwise fail a drop that worked.
- Kill switch, default on for this desktop: `MEMORY_GUARD_RECLAIM_ENABLED=false` in the private env file or the process
  environment (or `check --no-reclaim-enabled` for one run). To remove everything:
  `Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false`.
- The tool still never touches a process and never starts WSL. One residual race: the distro stopping between the list
  and the drop would let `wsl -d` start it; the window is milliseconds and the distro is the one the owner runs.

### Alternatives

- `autoMemoryReclaim=gradual` (or `dropcache`) in `.wslconfig`: the cleaner fix at the source, but the owner did not
  approve changing `.wslconfig`; it stays untouched.
- Capping the VM memory or swap in `.wslconfig`: same reason, and it shrinks the workload instead of the waste.
- Dropping the cache from the guest on a systemd timer: it has no knowledge of host commit, so it either drops
  needlessly (losing warm cache) or too late; the host-side trigger acts only under measured pressure.
- Alert only (0.1.x): each incident needed a human or an agent to run the same command.

### Consequences

- Under pressure the guest loses its page cache: a burst of disk reads while it refills (about 20 minutes).
- At most 6 drops per hour bound the cost of a persistent condition; a drop that no longer helps still alerts, because
  the alert condition is unchanged.
- The tool is no longer read-only; the safety boundary is the guard list above plus the kill switch.

### Verification

- Tests in `tools/memory-guard/tests/test_reclaim.py`: running versus stopped distro, kill switch, minimum interval,
  6 per hour, timeout, nonzero exit, missing counter, drop-before-alert order, both failures reported, settle bound,
  recovery message, malformed and trimmed log, `wsl.exe` argument vectors.
- After merge: the task registered from the merged tree and a forced-threshold run
  (`check --min-free-virtual-gb 100000 --state-dir <temp>` with `MEMORY_GUARD_RECLAIM_SAMPLES=1`) must drop once and
  record the numbers.

## Addendum 2026-11-25: cause attribution of low headroom (0.3.0)

### Context

The research note `vmmemWSL commit swings follow Ollama GPU model load and unload 2026-11-25` (Agent Memory vault) showed
that the 10 to 26 GB swings of `vmmemWSL` private bytes on the desktop are host commit charged 1:1 for the GPU device
allocations of the Ollama runner. A model loads on a chat request and unloads 5 minutes after the last one. The
Hyper-V allocation stayed flat at 15.9 GB while private bytes fell 10.1 GB, so the guest page cache is a minor part
(2.5 GB at most) and `drop_caches` cannot free the rest. Version 0.2.0 dropped caches on that premise and its alerts
said nothing about the cause, so a GPU-driven alarm read as "low free RAM from cache".

### Decision

- Attribute only low free virtual memory (host commit), and only when an alert is due or the cache drop is eligible, so
  a sustained breach does not cost an HTTP call and a PDH read on every run. A low free RAM breach alone gets no cause
  line: GPU commit explains free virtual memory, not physical RAM. The attribution prints in the alert as `cause: ...`:
  - `GPU model resident: <model> (<size>), unloads ~<N> min from now`: Ollama `GET /api/ps` lists a model with
    `size_vram > 0`; N comes from its `expires_at` (keep-alive expiry, which is the last request plus the keep-alive).
    The host GPU dedicated usage is appended when the counter is readable.
  - `GPU memory held without an Ollama model: another GPU consumer`: nothing resident in Ollama, GPU dedicated usage at
    or above `MEMORY_GUARD_GPU_OTHER_GB` (default 4).
  - `Ollama model resident in RAM, not on the GPU`: a loaded model with `size_vram == 0`.
  - `guest page cache is the candidate (...inferred, not measured)`: both signals readable, no model resident, GPU
    quiet. It is an inference by exclusion and the text says so; the top processes in the alert show the rest.
  - `cause unknown: <reason>`: the endpoint is unset, down, slow or answers an unexpected shape, or the GPU counter is
    missing while no model is resident. Never a guessed attribution; both reasons are listed when both signals fail.
- The WSL cache drop stays enabled and unchanged for every cause except one: while a GPU model is resident the drop is
  skipped, because a guest cache drop cannot release host commit charged for GPU allocations, and repeating it only
  costs a refill of the cache. The alert says `WSL cache drop skipped`. A drop is still allowed when the cause is
  cache, another GPU consumer or unknown (harmless, the 0.2.0 guards still apply).
- Host GPU dedicated memory is read from the PDH counter `\GPU Adapter Memory(*)\Dedicated Usage`, summed over
  adapters, through pywin32 `win32pdh.AddEnglishCounter` (works on any display language; the desktop runs Spanish).
- The Ollama endpoint is `MEMORY_GUARD_OLLAMA_URL` in the private env file (typed setting, no default, no credentials);
  timeout `MEMORY_GUARD_OLLAMA_TIMEOUT_S` (5 s).
- Attribution failures never fail the run: the alert carries `cause unknown: <reason>` instead (explicit, visible),
  while the alert path and drop failures keep their nonzero exit. The attribution boundary catches every exception
  (a missing pywin32, a malformed URL, a naive timestamp) because a probe bug must not silence the watchdog; the
  exception type and message go into the alert. Probe messages carry the HTTP status or exception type, never the URL
  (the alert reaches a mailbox).
- The drop is skipped only when it would otherwise have been eligible (enabled, sustained, interval and hourly guards),
  and only then does the alert say `WSL cache drop skipped`; `reclaimer.eligible()` exposes those guards plus the running-distro check, and counts an unreadable log or an
  unknown distro state as not eligible (the real drop path still reports it). The exception text of an unexpected
  attribution failure is reduced to its type name.
- `MEMORY_GUARD_OLLAMA_URL` must point at the Ollama that serves this host's GPU: a remote Ollama would suppress the
  local drop for a model that is not on this host.

### Libraries

| Library | Stars (2026-11-25) | Provider | Licence | Use |
|---|---|---|---|---|
| pywin32 | 5,639 | mhammond | PSF | PDH counter (`win32pdh`); Windows only marker in `pyproject.toml` |
| httpx | 15,855 | encode | BSD-3-Clause | `GET /api/ps` with timeouts and a mockable transport |

### Alternatives

- Shell out to `typeperf` or `nvidia-smi`: localized counter names and a parsed text format; rejected for the PDH API.
- Read only Ollama or only the GPU counter: Ollama alone cannot see other GPU users; the counter alone cannot say
  whether the memory is Ollama's or when it unloads. Both are read, each failure is explicit.
- Shorten `OLLAMA_KEEP_ALIVE` or lower `OLLAMA_CONTEXT_LENGTH` (remediations 2 and 3 of the research note): changes the
  Ollama service for its callers; left to the owner's decision and not part of this tool.
- Attribute cache by measuring guest `Cached` through `wsl.exe`: starts a process in the guest on every breached run;
  not needed to avoid the wrong claim, so the cache case is labeled as an inference.

### Consequences

- An alert during a model load now says which model, how large and when it unloads, so nobody chases the page cache.
- During a resident model no WSL process is started by the guard (no needless `drop_caches`).
- Each breached run costs one HTTP call (5 s bound) and one PDH read.

### Verification

- Tests in `tools/memory-guard/tests/test_attribution.py`: model resident with size and unload time, no-expiry model,
  counter missing with a model resident, cache-only, another GPU consumer, endpoint down, both signals missing,
  counter missing with no model, unset URL, HTTP error, missing required field, malformed body, connection failure,
  alert text and drop skipped for a resident model only when the drop was eligible, drop still run for cache and
  unknown, RAM-only breach not attributed, no attribution work before the condition is sustained, CPU-resident model,
  naive timestamp and unexpected probe exception reported as unknown, URL kept out of probe errors, PDH read through a
  fake `win32pdh` (sum, no instances, counter error, missing pywin32, query closed) and one live read on Windows.
- After deploy: a forced-threshold run (`check --min-free-virtual-gb 100000 --state-dir <temp>` with the alert command
  pointed at a print-only sink) must print the attribution line without touching WSL.

## Addendum 2026-11-27: commit headroom published to Prometheus (0.4.0)

### Context

A LiteLLM pre-call hook must refuse or reroute Ollama requests when the desktop is short of commit headroom, because a
model load charges host commit 1:1 for its GPU allocations (addendum 0.3.0). The hook reads Prometheus, and Prometheus
has no Windows host signal: no `windows_exporter` runs on the desktop. The guard already measures the right value
(free virtual memory: commit limit minus commit charge, through `GetPerformanceInfo`). The node-exporter of the cluster
runs on the `gabriel-pc-wsl` node with `--collector.textfile.directory=/rootfs/var/lib/node_exporter/textfile_collector`
(`stacks/main/monitoring.yml`), so a file at `/var/lib/node_exporter/textfile_collector/` inside the guest is scraped.

### Decision

- New command `memory-guard publish-headroom`, run by a separate Task Scheduler task `memory-guard-headroom` every
  minute (`deploy/register-headroom-task.ps1`, hidden, BelowNormal, one-minute execution limit).
- It writes `/var/lib/node_exporter/textfile_collector/memory_guard_commit.prom` in the distro of
  `MEMORY_GUARD_WSL_DISTRO` with exactly two gauges, each with `# HELP` and `# TYPE ... gauge`:
  `memory_guard_commit_headroom_bytes{host="<label>"}` (integer bytes) and
  `memory_guard_commit_sample_timestamp_seconds{host="<label>"}` (unix seconds, float). The label comes from
  `MEMORY_GUARD_HEADROOM_HOST_LABEL` (default `gabriel-pc`, restricted to `[A-Za-z0-9_.:-]+` so no escaping is needed).
- The write is atomic: `wsl.exe -d <distro> -u root -- sh -c 'cat > <file>.tmp && mv <file>.tmp <file>'`, the content
  on stdin (never in argv), 30 s timeout (`MEMORY_GUARD_HEADROOM_TIMEOUT_S`). A nonzero exit, a timeout or a missing
  `wsl.exe` raises `PublishError`; the command exits 1 with a plain one-line reason on stderr.
- WSL is never started: the existing `wsl --list --running --quiet` check runs first; a stopped distro exits 0 with
  `distro_not_running`. A negative or non-integer headroom, or a non-positive timestamp, is a `ProbeError` (exit 1) and
  nothing is written.
- Feature flag `MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED`, default false: the command prints `disabled` and exits 0 without
  probing or touching WSL. The feature ships dark and is enabled in the private env file of the desktop.
- The consumer owns freshness: it compares the timestamp gauge with the current time and fails closed when the metric
  is stale or absent.

### Alternatives

- `windows_exporter` MSI on the desktop: a second always-on service and a host install plus a firewall route from the
  cluster to Windows; the guard already has the value.
- Prometheus Pushgateway: not deployed in the stack; a new service only for one host signal.
- Prometheus remote-write receiver: not enabled, and opening a write path into Prometheus is a larger trust change.
- Writing the file from the existing 5-minute `check` task: couples the alert cadence to the metric cadence and makes a
  publish failure fail the watchdog; a separate task keeps both independent.

### Consequences

- The value is up to 60 s (task cadence) plus one scrape interval old; the consumer must tolerate that and treat older
  samples as stale.
- When WSL is down the file is not refreshed and the node-exporter on that node is gone too, so the metric is absent.
  That is acceptable: Ollama runs in the same guest and is down as well.
- One `wsl.exe --list` and, while running, one short `sh` in the guest per minute.

### Verification

- Tests in `tools/memory-guard/tests/test_publish_headroom.py`: flag off touches nothing, distro not running writes
  nothing, exact textfile text, writer failure and CLI exit 1 with the reason, content passed on stdin and absent from
  argv, `cat > tmp && mv` argument vector, nonzero exit and timeout as `PublishError`, negative and malformed headroom,
  bad timestamp, unsafe host label.
- After deploy: with the flag on, run `memory-guard publish-headroom --env-file <private env>` once, then query
  `memory_guard_commit_headroom_bytes{host="gabriel-pc"}` in Prometheus and check that
  `time() - memory_guard_commit_sample_timestamp_seconds` stays under 120 s.

## Addendum 2026-11-27: non-paged pool condition and alert de-duplication (0.5.0)

### Context

On 2026-11-27 the desktop reported "low free RAM" about every 30 minutes and the agent-bridge mailbox filled with about
100 identical notices. The signal was real, not an artifact: available memory (free plus standby, `psutil` `available`,
`GetPerformanceInfo` `PhysicalAvailable`) was 0.25-0.7 GiB with 3k-65k page reads per second, because the kernel
non-paged pool held 10.05 GiB (baseline 0.3-1.5 GiB), of which about 6.3 GiB were leaked `File` objects. The label "free
RAM" was loose, the symptom repeated while the cause (the pool) stayed unchanged, and the alert gave a reader neither
the thrash nor the leak. Evidence: the 2026-11-27 desktop memory investigation, whose measurements are inlined above.

### Decision

- The RAM alert is named `available RAM (free + standby)` everywhere (alert, recovery, README).
- New condition `nonpaged_pool`: the pool is above `MEMORY_GUARD_MAX_NONPAGED_PCT` (default 20) percent of physical RAM
  (`GetPerformanceInfo` `PhysicalTotal`; about 6.2 GiB on 31 GiB), strictly above, in `MEMORY_GUARD_SAMPLES` consecutive
  samples. Its alert text is `low kernel non-paged pool` with the pool, its share of physical RAM and the limit.
- Every alert body carries `page reads/s` (WMI `Win32_PerfFormattedData_PerfOS_Memory.PageReadsPersec`, read in process
  through pywin32 because `Get-Counter` fails on this host with error c0000bb8) and the live `File` pool tag allocations
  (`NtQuerySystemInformation(SystemPoolTagInformation)`, allocations minus frees). A reading that cannot be taken
  (WMI error, malformed or negative value, STATUS_ACCESS_DENIED without elevation, tag absent, buffer malformed) prints
  `unknown (<reason>)`; it is never replaced by a number, and the alert still goes out.
- De-duplication by state change: the pool condition alerts once when it becomes active, again only when the pool grew
  by `MEMORY_GUARD_NONPAGED_GROWTH_GB` (default 1) since its last alert, and as a reminder every
  `MEMORY_GUARD_NONPAGED_REMINDER_H` (default 6) hours. While the pool alert is active, the pool is over its limit and it
  has not grown a step, the low-RAM alert uses the same 6 hour reminder instead of the 30 minute `alert_interval`. Low
  free virtual memory, and low RAM without an active pool, keep the 30 minute cadence. Recovery messages are unchanged
  (one per state change). A pool that recovers and breaches again alerts at once (the recovery clears its last-alert
  time); the reminder paces only an unbroken breach. A growth step waits at most the 30 minute `alert_interval` after
  the previous alert.
- `PageReadsPersec` comes from the formatted WMI class, a rate the OS derives between its own samples, so a `0` is a
  reading, not proof of an idle disk; the raw counter delta is a possible refinement. Pool tag buffer sizing is bounded
  (a size request that does not grow, or more than five attempts, is an explicit `Unknown`). Any unexpected diagnostics
  failure is printed as `unknown (<type>: <message>)` so the alert is never lost with it.
- State: each condition row gains an optional `reference` (the pool size at its last alert). A state file written by
  0.4.0 has no row for the new condition; the loader starts that row fresh instead of failing. A missing row for any
  other condition, or a malformed row, is a `StateError`.

### Libraries

- `pywin32` (mhammond/pywin32, about 5k GitHub stars, already a dependency since 0.3.0, PSF licence) for WMI.
- Pool tags use `ctypes` on `ntdll`: no maintained Python library wraps `SystemPoolTagInformation`, and `psutil` (about
  10k stars) exposes only the totals.

### Alternatives

- Keep one alert and only rename it: leaves the mailbox flood and the missing cause.
- Silence the RAM alert while the pool is active: hides a real, changing symptom; the 6 hour reminder and the growth step
  keep it visible.
- Read the counter with `Get-Counter` or a PowerShell subprocess: fails here (c0000bb8) and adds a process per run.
- Use `psutil` for page reads: it has no `Page Reads/sec` rate.
- Fixed 6.2 GiB limit: the percentage follows the machine RAM; the setting stays overridable.

### Consequences

- At most about two alerts a day during a steady leak (pool and RAM in one message at the reminder), plus one per
  one-GiB growth step. A reader sees thrash (page reads) and leak (`File` objects) in the same message.
- `File` tag counting may need elevation in some sessions; the guard then says so in the alert (`unknown (...)`), which
  is the evidence for running the Task Scheduler entry elevated if that value is wanted.
- The deployed copy is replaced from the repository; no re-registration of the scheduled task is needed because the
  command line is unchanged.

### Verification

- `tools/memory-guard/tests/test_nonpaged.py`: boundary values around the limit, the renamed label, the combined first
  alert, no repeat for six hours across simulated runs, the reminder at exactly six hours, growth just under and at the
  step, low RAM alone repeating every 30 minutes, recovery and re-arm, state migration from 0.4.0, counter parsing
  (valid, string, float, `None`, boolean, negative, text, list, bytes), pool-tag table parsing (grow-and-retry, runaway
  size, access denied, other status, short buffer, frees above allocations, missing tag), independent degradation of the
  two readings to `unknown (<reason>)`, and unexpected exceptions staying visible.
- After deploy: a forced run on the installed copy with a print-only alert command and a temporary state directory
  (`check --max-nonpaged-pct 5 --min-free-ram-gb 100000 --state-dir <temp>`, two runs) must print the new texts and real
  `page reads/s` and `File` values or `unknown (<reason>)`, and send nothing to the bridge.
