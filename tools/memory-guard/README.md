# memory-guard

Windows memory-pressure watchdog (touches no process). Alerts when free virtual memory is under 8 GiB or free RAM under
1 GiB in two consecutive samples, with the top 10 processes by private bytes and the non-paged pool size. See
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
