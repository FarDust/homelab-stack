# memory-guard

Read-only Windows memory-pressure watchdog. Alerts when free virtual memory is under 8 GiB or free RAM under
1 GiB in two consecutive samples, with the top 10 processes by private bytes and the non-paged pool size. See
`docs/adr/memory_guard_adr.md`.

```
uv run --project tools/memory-guard memory-guard sample
uv run --project tools/memory-guard memory-guard check --env-file <private env>
```

Install: `deploy/register-windows-task.ps1 -ProjectDir <dir> -EnvFile <env>` (every 5 minutes, hidden, BelowNormal).
Uninstall: `Unregister-ScheduledTask -TaskName memory-guard -Confirm:$false`.
Settings (`MEMORY_GUARD_*`) are in `deploy/memory-guard.env.example`.
