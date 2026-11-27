# memory-guard

Windows memory-pressure watchdog (touches no process). Alerts when free virtual memory is under 8 GiB, available RAM (free + standby) under
1 GiB, or the kernel non-paged pool is over 20 % of physical RAM, in two consecutive samples, with the top 10 processes by private bytes and the non-paged pool size. See
`docs/adr/memory_guard_adr.md`.

```
uv run --project tools/memory-guard memory-guard sample
uv run --project tools/memory-guard memory-guard check --env-file <private env>
```

Install: `deploy/register-windows-task.ps1 -ProjectDir <dir> -EnvFile <env>` (every 5 minutes, hidden, BelowNormal).
Uninstall: `Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false`.
Settings (`MEMORY_GUARD_*`) are in `deploy/memory-guard.env.example`.

Opt-in remediation (on by default for the desktop that approved it): under sustained low free virtual memory, with the
WSL distro already running, memory-guard drops the WSL guest page cache (at most 6 per hour, 10 minutes apart, 60 s
timeout) and records free virtual, free RAM and `vmmemWSL` before and after in the alert and in
`<state-dir>/reclaim.jsonl`. It never starts WSL and never touches `.wslconfig`. Disable it with
`MEMORY_GUARD_RECLAIM_ENABLED=false` in the env file (or the process environment), or remove the whole task with
`Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false`.

Cause attribution (0.3.0): every alert carries a `cause:` line. With `MEMORY_GUARD_OLLAMA_URL` set (private env file) the
guard reads Ollama `GET /api/ps` and the host `\GPU Adapter Memory(*)\Dedicated Usage` counter and names a resident GPU
model (with its size and unload time), another GPU consumer, guest page cache (an inference) or `cause unknown: <reason>`.
The cache drop is skipped while a GPU model is resident.

Commit-headroom metric (0.4.0): `memory-guard publish-headroom --env-file <private env>` writes Windows free virtual
memory into the running WSL guest as the node-exporter textfile
`/var/lib/node_exporter/textfile_collector/memory_guard_commit.prom` (gauges `memory_guard_commit_headroom_bytes` and
`memory_guard_commit_sample_timestamp_seconds`, label `host`). It is off until `MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED=true`,
never starts WSL, and exits 1 when the write fails. Install: `deploy/register-headroom-task.ps1 -ProjectDir <dir>
-EnvFile <env>` (every minute, hidden, BelowNormal). Uninstall:
`Unregister-ScheduledTask -TaskName memory-guard-headroom -Confirm:$false`.

Non-paged pool (0.5.0): the pool is its own condition (`MEMORY_GUARD_MAX_NONPAGED_PCT`, default 20). Every alert shows
`page reads/s` and the live `File` pool tag count, or `unknown (<reason>)` when a reading is unavailable. The pool alert
repeats only after 1 GiB of growth or every 6 hours (`MEMORY_GUARD_NONPAGED_GROWTH_GB`, `MEMORY_GUARD_NONPAGED_REMINDER_H`),
and the low-RAM alert follows that reminder while the pool is active and unchanged.
