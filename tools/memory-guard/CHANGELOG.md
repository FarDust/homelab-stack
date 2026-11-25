# Changelog

## 0.3.0

- Cause attribution in every alert: when headroom is low the guard reads the host GPU dedicated usage (PDH counter
  `\GPU Adapter Memory(*)\Dedicated Usage` through pywin32) and the Ollama loaded-model list (`GET /api/ps` on
  `MEMORY_GUARD_OLLAMA_URL`) and prints `cause: GPU model resident: <model> (<size>), unloads ~<N> min from now`,
  `cause: guest page cache (...)`, `cause: GPU memory held without an Ollama model...` or
  `cause unknown: <reason>`. A missing counter or an unreachable endpoint is reported, never guessed.
- Only low free virtual memory is attributed (a RAM-only breach gets no cause line), and only when an alert is due or
  the drop is eligible. A model resident in RAM (no VRAM) is named as such; the cache case is labeled a candidate.
- The WSL page-cache drop is skipped while a GPU model is resident (it cannot free GPU commit); the alert says so only
  when the drop would otherwise have run. Any probe failure becomes `cause unknown: <reason>` and the alert still goes
  out; probe errors never include the endpoint URL.
- New settings: `MEMORY_GUARD_OLLAMA_URL`, `MEMORY_GUARD_OLLAMA_TIMEOUT_S`, `MEMORY_GUARD_GPU_OTHER_GB`. New
  dependencies: httpx, pywin32 (Windows). See `docs/adr/memory_guard_adr.md` (addendum 2026-11-25, 0.3.0).

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
