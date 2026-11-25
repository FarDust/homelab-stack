# Changelog

## 0.1.0

- First release: `check` and `sample` commands; commit charge, free RAM and non-paged pool read through
  `GetPerformanceInfo` and psutil; alert after two consecutive low samples, one alert per condition per 30 minutes,
  recovery message; read-only (never touches a process); Task Scheduler launcher. See `docs/adr/memory_guard_adr.md`.
