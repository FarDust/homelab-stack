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
  than 6 attempts in the last hour (failed attempts count). The drop is `wsl.exe -d <distro> -u root -- sh -c ...`
  in a subprocess with a 60 s timeout.
- Free virtual, free RAM and `vmmemWSL` private bytes are read before and after (the after reading polls the counters
  for up to 20 s until `vmmemWSL` shrank by 1 GiB: a bound, not a fixed wait). Both go into the alert or recovery
  message and one line of `<state-dir>/reclaim.jsonl` (trimmed to 500 lines past 1000).
- The drop runs before the alert is posted, so a slow alert path (the agent-bridge post) never delays it.
- Failure is explicit: `wsl.exe` missing, a nonzero exit, a timeout, a missing `vmmemWSL` counter or an unreadable log
  exit 1 with the cause and a recovery hint on stderr; the alert still goes out, carrying the failure.
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
