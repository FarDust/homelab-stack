"""Publish Windows commit headroom into the running WSL guest for node-exporter (docs/adr/memory_guard_adr.md, 0.4.0)."""

from __future__ import annotations

from memory_guard.domain.headroom import HeadroomReading, PublishOutcome, PublishStatus, render_textfile
from memory_guard.domain.ports import Clock, DistroStatus, MemoryProbe, TextfileWriter


class PublishHeadroom:
    def __init__(
        self,
        enabled: bool,
        probe: MemoryProbe,
        distro: DistroStatus,
        writer: TextfileWriter,
        clock: Clock,
        host_label: str,
    ) -> None:
        self._enabled, self._probe, self._distro = enabled, probe, distro
        self._writer, self._clock, self._host_label = writer, clock, host_label

    def __call__(self) -> PublishOutcome:
        if not self._enabled:
            return PublishOutcome(PublishStatus.DISABLED)
        # Never start WSL: an absent metric while the guest is down is the consumer's fail-closed case.
        if not self._distro.is_running():
            return PublishOutcome(PublishStatus.DISTRO_NOT_RUNNING)
        sample = self._probe.sample()
        reading = HeadroomReading(sample.free_virtual, self._clock.now().timestamp())
        self._writer.write(render_textfile(reading, self._host_label))
        return PublishOutcome(PublishStatus.PUBLISHED, reading)
