"""One guard run: sample, update state, remediate (opt-in), alert on sustained pressure, announce recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from memory_guard.domain.errors import GuardError
from memory_guard.domain.models import (
    Attribution,
    Condition,
    GuardState,
    MemorySample,
    ReclaimRecord,
    Thresholds,
    gib,
    show,
)
from memory_guard.domain.ports import (
    AlertSink,
    CauseAttributor,
    Clock,
    MemoryProbe,
    PoolDiagnosticsProbe,
    ProcessLister,
    Reclaimer,
    StateStore,
)

LABEL = {
    Condition.VIRTUAL: "free virtual memory",
    Condition.RAM: "available RAM (free + standby)",
    Condition.NONPAGED: "kernel non-paged pool",
}


@dataclass(frozen=True)
class CheckResult:
    sample: MemorySample
    alerted: tuple[Condition, ...]
    recovered: tuple[Condition, ...]
    reclaim: ReclaimRecord | None = None


class CheckMemory:
    def __init__(
        self,
        probe: MemoryProbe,
        processes: ProcessLister,
        sink: AlertSink,
        store: StateStore,
        clock: Clock,
        thresholds: Thresholds,
        host: str,
        top_n: int = 10,
        reclaimer: Reclaimer | None = None,
        attributor: CauseAttributor | None = None,
        diagnostics: PoolDiagnosticsProbe | None = None,
    ) -> None:
        self._probe, self._processes, self._sink, self._store = probe, processes, sink, store
        self._clock, self._t, self._host, self._top_n = clock, thresholds, host, top_n
        self._reclaimer, self._attributor, self._diagnostics = reclaimer, attributor, diagnostics

    def _body(self, sample: MemorySample, notes: list[str]) -> str:
        top, skipped = self._processes.top_by_private_bytes(self._top_n)
        lines = [
            f"commit {gib(sample.commit_used)} of {gib(sample.commit_limit)} (free virtual {gib(sample.free_virtual)})",
            f"available RAM (free + standby) {gib(sample.free_ram)}; non-paged pool {gib(sample.nonpaged_pool)} = "
            f"{sample.nonpaged_pool / sample.physical_total:.0%} of {gib(sample.physical_total)} physical RAM "
            f"(limit {gib(self._t.nonpaged_limit(sample))})",
        ]
        if self._diagnostics is not None:
            d = self._diagnostics()
            lines.append(f"page reads/s {show(d.page_reads_per_s)}; File pool tag objects {show(d.file_pool_objects)}")
        lines.append(f"top {len(top)} processes by private bytes ({skipped} unreadable):")
        lines += [f"  {p.pid} {p.name} {gib(p.private_bytes)}" for p in top]
        lines += notes
        return "\n".join(lines)

    def _reclaim(
        self, sample: MemorySample, state: GuardState, cause: Attribution | None
    ) -> tuple[ReclaimRecord | None, GuardError | None]:
        """Run the opt-in cache drop before any alert: a slow or failing alert path never delays it."""
        if self._reclaimer is None:
            return None, None
        if cause is not None and cause.gpu_resident:
            # Host commit is charged for the GPU allocations; a guest cache drop cannot free it.
            return None, None
        try:
            return self._reclaimer(sample, state.conditions[Condition.VIRTUAL].consecutive), None
        except GuardError as exc:
            return None, exc

    def _drop_eligible(self, state: GuardState) -> bool:
        return self._reclaimer is not None and self._reclaimer.eligible(state.conditions[Condition.VIRTUAL].consecutive)

    def _pool_unchanged(self, state: GuardState, sample: MemorySample) -> bool:
        """The pool alert is out, the pool is still over its limit and has not grown a step since that alert."""
        pool = state.conditions[Condition.NONPAGED]
        if not pool.active or pool.reference is None:
            return False
        over = sample.nonpaged_pool > self._t.nonpaged_limit(sample)
        return over and sample.nonpaged_pool - pool.reference < self._t.nonpaged_growth

    def _interval(self, cond: Condition, state: GuardState, sample: MemorySample) -> timedelta:
        """Repeat cadence: the pool reminds every 6 h unless it grew a step; low RAM follows it while the pool explains it."""
        if cond is Condition.NONPAGED:
            pool = state.conditions[cond]
            grown = pool.reference is not None and sample.nonpaged_pool - pool.reference >= self._t.nonpaged_growth
            return self._t.alert_interval if grown else self._t.nonpaged_reminder
        if cond is Condition.RAM and self._pool_unchanged(state, sample):
            return self._t.nonpaged_reminder
        return self._t.alert_interval

    def _attribute(self, breached: dict[Condition, bool], due: list, eligible: bool) -> Attribution | None:
        """Attribute only low free virtual memory (host commit), and only when an alert or a drop is possible."""
        if self._attributor is None or not breached[Condition.VIRTUAL]:
            return None
        if Condition.VIRTUAL in due or eligible:
            return self._attributor()
        return None

    def __call__(self) -> CheckResult:
        sample = self._probe.sample()
        now = self._clock.now()
        state: GuardState = self._store.load()
        breached = self._t.breached(sample)
        due: list = []
        recovered: list = []
        for cond, hit in breached.items():
            st = state.conditions[cond]
            st.consecutive = st.consecutive + 1 if hit else 0
            if hit and st.consecutive >= self._t.samples:
                if st.last_alert is None or now - st.last_alert >= self._interval(cond, state, sample):
                    due.append(cond)
            elif not hit and st.active:
                recovered.append(cond)
        # Persist the counters first: a failed alert keeps them and retries on the next run.
        self._store.save(state)
        eligible = self._drop_eligible(state)
        cause = self._attribute(breached, due, eligible)
        record, reclaim_error = self._reclaim(sample, state, cause)
        notes = [cause.line] if cause else []
        if record:
            notes.append(record.summary())
        elif reclaim_error:
            notes.append(f"WSL cache drop failed: {reclaim_error}")
        elif cause is not None and cause.gpu_resident and eligible:
            notes.append("WSL cache drop skipped: a resident GPU model is not guest cache, a drop cannot free it")
        try:
            self._notify(sample, state, now, due, recovered, notes)
        except GuardError as exc:
            if reclaim_error is not None:
                raise GuardError(f"{reclaim_error}; additionally the alert path failed: {exc}") from exc
            raise
        if reclaim_error is not None:
            raise reclaim_error
        return CheckResult(sample, tuple(due), tuple(recovered), record)

    def _notify(
        self, sample: MemorySample, state: GuardState, now: datetime, due: list, recovered: list, notes: list[str]
    ) -> None:
        if due:
            names = ", ".join(LABEL[c] for c in due)
            # Record the attempt time before sending: a path that delivers but fails its receipt would otherwise
            # repeat the alert every run. The failure still exits nonzero; the retry waits one interval.
            for c in due:
                state.conditions[c].last_alert = now
            if Condition.NONPAGED in due:
                state.conditions[Condition.NONPAGED].reference = sample.nonpaged_pool
            self._store.save(state)
            self._sink.send(f"[memory-guard] {self._host}: low {names}\n{self._body(sample, notes)}")
            for c in due:
                state.conditions[c].active = True
            self._store.save(state)
        if recovered:
            names = ", ".join(LABEL[c] for c in recovered)
            last = self._reclaimer.last_summary() if self._reclaimer else None
            self._sink.send(
                f"[memory-guard] {self._host}: recovered {names}; free virtual {gib(sample.free_virtual)}, "
                f"available RAM (free + standby) {gib(sample.free_ram)}, non-paged pool {gib(sample.nonpaged_pool)}"
                + (f"\n{last}" if last else "")
            )
            for c in recovered:
                state.conditions[c].active = False  # keep last_alert: a flap stays inside the rate limit
            self._store.save(state)
