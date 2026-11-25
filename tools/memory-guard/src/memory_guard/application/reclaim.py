"""Opt-in remediation: drop the WSL guest page cache under sustained low free virtual memory, with strict guards."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from memory_guard.domain.errors import GuardError
from memory_guard.domain.models import GIB, MemorySample, ReclaimPolicy, ReclaimRecord, ReclaimSnapshot
from memory_guard.domain.ports import Clock, MemoryProbe, ReclaimLog, VmmemProbe, WslControl

POLL_S = 2.0
RELEASE_MIN = GIB  # the settle poll ends once vmmemWSL has shrunk by this much


class ReclaimWslCache:
    def __init__(
        self,
        wsl: WslControl,
        vmmem: VmmemProbe,
        probe: MemoryProbe,
        log: ReclaimLog,
        clock: Clock,
        policy: ReclaimPolicy,
        sleep: Callable[[float], None],
    ) -> None:
        self._wsl, self._vmmem, self._probe, self._log = wsl, vmmem, probe, log
        self._clock, self._policy, self._sleep = clock, policy, sleep

    def last_summary(self) -> str | None:
        recent = self._log.recent(self._clock.now() - timedelta(hours=1))
        return max(recent, key=lambda r: r.at).summary() if recent else None

    def _snapshot(self, sample: MemorySample) -> ReclaimSnapshot:
        return ReclaimSnapshot(sample.free_virtual, sample.free_ram, self._vmmem.private_bytes())

    def _settled_after(self, before: ReclaimSnapshot) -> ReclaimSnapshot:
        # Poll the observed counters (bounded by settle_s) instead of sleeping a fixed time: the host releases
        # the VM's memory a moment after the guest drops its cache.
        waited = 0.0
        while True:
            after = self._snapshot(self._probe.sample())
            if before.vmmem_private - after.vmmem_private >= RELEASE_MIN or waited >= self._policy.settle_s:
                return after
            self._sleep(POLL_S)
            waited += POLL_S

    def _guards_allow(self, consecutive_low: int) -> bool:
        p, now = self._policy, self._clock.now()
        if not p.enabled or consecutive_low < p.samples:
            return False
        recent = self._log.recent(now - timedelta(hours=1))
        if len(recent) >= p.max_per_hour or (recent and now - max(r.at for r in recent) < p.min_interval):
            return False
        return self._wsl.is_running()  # a stopped distro is never started

    def eligible(self, consecutive_low: int) -> bool:
        """Would a drop run now. An unreadable log or an unknown distro state counts as no: `__call__` reports it."""
        try:
            return self._guards_allow(consecutive_low)
        except GuardError:
            return False

    def __call__(self, sample: MemorySample, consecutive_low: int) -> ReclaimRecord | None:
        """Return the record of a successful drop, None when a guard says no; raise GuardError on failure."""
        if not self._guards_allow(consecutive_low):
            return None
        now = self._clock.now()
        before = self._snapshot(sample)  # a missing vmmemWSL counter raises ProbeError before anything runs
        try:
            self._wsl.drop_cache()
            record = ReclaimRecord(now, True, before, self._settled_after(before))
        except GuardError as exc:
            self._log.append(ReclaimRecord(now, False, before, None, str(exc)))
            raise
        self._log.append(record)
        return record
