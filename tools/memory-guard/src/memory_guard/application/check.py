"""One guard run: sample, update state, alert on sustained pressure, announce recovery."""

from __future__ import annotations

from dataclasses import dataclass

from memory_guard.domain.models import Condition, GuardState, MemorySample, Thresholds, gib
from memory_guard.domain.ports import AlertSink, Clock, MemoryProbe, ProcessLister, StateStore

LABEL = {Condition.VIRTUAL: "free virtual memory", Condition.RAM: "free RAM"}


@dataclass(frozen=True)
class CheckResult:
    sample: MemorySample
    alerted: tuple[Condition, ...]
    recovered: tuple[Condition, ...]


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
    ) -> None:
        self._probe, self._processes, self._sink, self._store = probe, processes, sink, store
        self._clock, self._t, self._host, self._top_n = clock, thresholds, host, top_n

    def _body(self, sample: MemorySample) -> str:
        top, skipped = self._processes.top_by_private_bytes(self._top_n)
        lines = [
            f"commit {gib(sample.commit_used)} of {gib(sample.commit_limit)} (free virtual {gib(sample.free_virtual)})",
            f"free RAM {gib(sample.free_ram)}; non-paged pool {gib(sample.nonpaged_pool)}",
            f"top {len(top)} processes by private bytes ({skipped} unreadable):",
        ]
        lines += [f"  {p.pid} {p.name} {gib(p.private_bytes)}" for p in top]
        return "\n".join(lines)

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
                if st.last_alert is None or now - st.last_alert >= self._t.alert_interval:
                    due.append(cond)
            elif not hit and st.active:
                recovered.append(cond)
        # Persist the counters first: a failed alert keeps them and retries on the next run.
        self._store.save(state)
        if due:
            names = ", ".join(LABEL[c] for c in due)
            self._sink.send(f"[memory-guard] {self._host}: low {names}\n{self._body(sample)}")
            for c in due:
                state.conditions[c].active, state.conditions[c].last_alert = True, now
            self._store.save(state)
        if recovered:
            names = ", ".join(LABEL[c] for c in recovered)
            self._sink.send(
                f"[memory-guard] {self._host}: recovered {names}; free virtual {gib(sample.free_virtual)}, "
                f"free RAM {gib(sample.free_ram)}, non-paged pool {gib(sample.nonpaged_pool)}"
            )
            for c in recovered:
                state.conditions[c].active, state.conditions[c].last_alert = False, None
            self._store.save(state)
        return CheckResult(sample, tuple(due), tuple(recovered))
