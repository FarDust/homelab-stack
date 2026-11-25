# Changelog

## 0.2.0

- Opt-in WSL page-cache drop (default on for the desktop that approved it). When free virtual memory is under the
  threshold in two consecutive samples, the distro is already running, the last attempt is over 10 minutes old and
  fewer than 6 attempts ran in the last hour, a root `sync; drop_caches; compact_memory` runs inside the distro through
  `wsl.exe` with a 60 s timeout. Free virtual, free RAM and `vmmemWSL` private bytes before and after go into the alert
  or recovery message and into `reclaim.jsonl` in the state directory. A failing, timing-out or unverifiable drop exits
  1 with an actionable cause; the drop runs before the alert, so a slow alert path never delays it. A stopped distro is
  never started and no process is touched. Kill switch: `MEMORY_GUARD_RECLAIM_ENABLED=false`. See
  `docs/adr/memory_guard_adr.md` (addendum 2026-11-25).

## 0.1.1

- A failed alert attempt now counts toward the 30-minute rate limit (the run still exits 1), so a path that delivers but fails its receipt cannot repeat the alert every 5 minutes.

## 0.1.0

- First release: `check` and `sample` commands; commit charge, free RAM and non-paged pool read through
  `GetPerformanceInfo` and psutil; alert after two consecutive low samples, one alert per condition per 30 minutes,
  recovery message; read-only (never touches a process); Task Scheduler launcher. See `docs/adr/memory_guard_adr.md`.
