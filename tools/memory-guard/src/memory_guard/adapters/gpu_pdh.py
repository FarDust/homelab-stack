r"""Host GPU dedicated memory through the Windows PDH counter `\GPU Adapter Memory(*)\Dedicated Usage` (pywin32)."""

from __future__ import annotations

import sys

from memory_guard.domain.errors import ProbeError

COUNTER = r"\GPU Adapter Memory(*)\Dedicated Usage"


class PdhGpuMemoryProbe:
    def dedicated_usage(self) -> int:
        if sys.platform != "win32":
            raise ProbeError("PDH GPU counters are only available on Windows")
        try:
            import win32pdh
        except ImportError as exc:
            raise ProbeError("pywin32 is not installed, GPU counter unavailable") from exc

        query = win32pdh.OpenQuery()
        try:
            # AddEnglishCounter takes the English path on any display language (this host runs Spanish).
            handle = win32pdh.AddEnglishCounter(query, COUNTER)
            win32pdh.CollectQueryData(query)
            values = win32pdh.GetFormattedCounterArray(handle, win32pdh.PDH_FMT_LARGE)
        except win32pdh.error as exc:
            raise ProbeError(f"GPU Adapter Memory counter unavailable: {exc}") from exc
        finally:
            win32pdh.CloseQuery(query)
        if not values:
            raise ProbeError("GPU Adapter Memory counter returned no adapter instances")
        return int(sum(values.values()))
