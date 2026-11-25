"""Name why headroom is low: a resident Ollama GPU model, another GPU consumer, guest page cache, or unknown."""

from __future__ import annotations

import math

from memory_guard.domain.errors import ProbeError
from memory_guard.domain.models import Attribution, CauseKind, gib
from memory_guard.domain.ports import Clock, GpuMemoryProbe, ModelResidencyProbe

NO_EXPIRY_S = 24 * 3600  # keep-alive -1 reports a far-future expiry


class AttributeCause:
    def __init__(self, gpu: GpuMemoryProbe, models: ModelResidencyProbe, clock: Clock, other_gpu_min: int) -> None:
        self._gpu, self._models, self._clock, self._other_gpu_min = gpu, models, clock, other_gpu_min

    def _gpu_reading(self) -> tuple[int | None, str | None]:
        try:
            return self._gpu.dedicated_usage(), None
        except ProbeError as exc:
            return None, str(exc)

    def __call__(self) -> Attribution:
        dedicated, gpu_error = self._gpu_reading()
        gpu_note = f"; host GPU dedicated {gib(dedicated)}" if dedicated is not None else ""
        try:
            loaded = self._models.loaded_models()
        except ProbeError as exc:
            reasons = [str(exc)] + ([gpu_error] if gpu_error else [])
            return Attribution(CauseKind.UNKNOWN, f"cause unknown: {'; '.join(reasons)}{gpu_note}")
        resident = [m for m in loaded if m.size_vram > 0]
        if resident:
            now = self._clock.now()
            parts = []
            for m in sorted(resident, key=lambda m: m.size_vram, reverse=True):
                left = (m.expires_at - now).total_seconds()
                when = (
                    "no scheduled unload"
                    if left > NO_EXPIRY_S
                    else f"unloads ~{max(1, math.ceil(left / 60))} min from now"
                )
                parts.append(f"{m.name} ({gib(m.size_vram)}), {when}")
            tail = f"; GPU counter unavailable: {gpu_error}" if gpu_error else gpu_note
            return Attribution(CauseKind.GPU_MODEL, f"GPU model resident: {'; '.join(parts)}{tail}")
        if dedicated is None:
            return Attribution(CauseKind.UNKNOWN, f"cause unknown: no Ollama model resident, {gpu_error}")
        if dedicated >= self._other_gpu_min:
            return Attribution(
                CauseKind.GPU_OTHER, f"GPU memory held without an Ollama model: another GPU consumer{gpu_note}"
            )
        return Attribution(
            CauseKind.PAGE_CACHE,
            f"guest page cache (no GPU model resident{gpu_note}; the cache is inferred, not measured)",
        )
