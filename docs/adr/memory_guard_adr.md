# Memory guard for the Windows desktop

Status: accepted, 2026-11-25. Implementation: `tools/memory-guard` (0.1.0).

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
- Alert path: an external command from `MEMORY_GUARD_ALERT_COMMAND` (a JSON argument list with a `{message}`
  placeholder), the agent-bridge helper's `post`. Success needs exit 0 and the `delivered` receipt in stdout; a
  failure exits 1 with the cause on stderr, does not mark the condition as alerted and is retried on the next run.
- Read-only: the tool never signals, kills or modifies a process, and starts neither WSL nor anything heavy.
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
