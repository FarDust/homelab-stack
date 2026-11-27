"""Non-paged pool condition, alert de-duplication and the pool diagnostics (docs/adr/memory_guard_adr.md, 0.5.0)."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory_guard.adapters.pool_diagnostics import (
    STATUS_ACCESS_DENIED,
    STATUS_INFO_LENGTH_MISMATCH,
    WindowsPoolDiagnostics,
    file_tag_objects,
    parse_counter,
)
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.application.check import CheckMemory
from memory_guard.domain.errors import ProbeError, StateError
from memory_guard.domain.models import (
    GIB,
    Condition,
    Measured,
    MemorySample,
    PoolDiagnostics,
    ProcessUsage,
    Thresholds,
    Unknown,
)

T0 = datetime(2026, 11, 27, 22, 0, tzinfo=UTC)
PHYS = 31 * GIB
LIMIT = int(0.20 * PHYS)  # about 6.2 GiB on this host


def sample(pool: int, free_ram: int = 5 * GIB) -> MemorySample:
    return MemorySample(30 * GIB, 78 * GIB, free_ram, pool, PHYS)


THRASH = sample(10 * GIB, free_ram=GIB // 4)  # the 2026-11-27 reading: 0.25 GiB available, 10 GiB pool
TH = Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30))


class Probe:
    def __init__(self, *samples: MemorySample) -> None:
        self.samples = list(samples)

    def sample(self) -> MemorySample:
        return self.samples.pop(0)


class Procs:
    def top_by_private_bytes(self, limit: int):
        return [ProcessUsage(1, "p.exe", GIB)], 0


class Sink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        return self.t


def diag(reads: object = Measured(3200), files: object = Measured(16_965_727)):
    return lambda: PoolDiagnostics(reads, files)  # type: ignore[arg-type]


def guard(tmp_path: Path, samples: list[MemorySample], sink: Sink, clock: Clock, diagnostics=None) -> CheckMemory:
    return CheckMemory(
        Probe(*samples), Procs(), sink, JsonStateStore(tmp_path / "s.json"), clock, TH, "host", diagnostics=diagnostics
    )


def run(tmp_path: Path, sink: Sink, clock: Clock, samples: list[MemorySample], diagnostics=None):
    """One persistent store, one fresh guard per run, as the Task Scheduler does."""
    return guard(tmp_path, samples, sink, clock, diagnostics)()


# --- the condition ---------------------------------------------------------------------------------------------


def test_pool_breach_is_strictly_above_twenty_percent_of_physical() -> None:
    assert TH.nonpaged_limit(sample(0)) == LIMIT
    assert TH.breached(sample(LIMIT))[Condition.NONPAGED] is False  # boundary: equal is not above
    assert TH.breached(sample(LIMIT + 1))[Condition.NONPAGED] is True
    assert TH.breached(sample(0))[Condition.NONPAGED] is False


def test_limit_is_configurable() -> None:
    tight = Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30), max_nonpaged_fraction=0.05)
    assert tight.breached(sample(2 * GIB))[Condition.NONPAGED] is True


def test_ram_alert_uses_the_available_ram_label(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    ram_only = sample(GIB, free_ram=GIB // 2)
    run(tmp_path, sink, clock, [ram_only])
    run(tmp_path, sink, clock, [ram_only])
    assert len(sink.sent) == 1
    assert "low available RAM (free + standby)" in sink.sent[0]
    assert "free RAM" not in sink.sent[0]


def test_pool_alert_names_the_condition_and_carries_the_diagnostics(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [sample(10 * GIB)], diag())
    result = run(tmp_path, sink, clock, [sample(10 * GIB)], diag())
    assert result.alerted == (Condition.NONPAGED,)
    text = sink.sent[0]
    assert "low kernel non-paged pool" in text
    assert "non-paged pool 10.00 GiB = 32% of 31.00 GiB physical RAM (limit 6.20 GiB)" in text
    assert "page reads/s 3,200; File pool tag objects 16,965,727" in text


def test_unreadable_diagnostics_print_unknown_with_the_reason_and_still_alert(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    bad = diag(Unknown("CIM query for PageReadsPersec failed: com_error"), Unknown("pool tags need elevation"))
    run(tmp_path, sink, clock, [THRASH], bad)
    run(tmp_path, sink, clock, [THRASH], bad)
    text = sink.sent[0]
    assert "page reads/s unknown (CIM query for PageReadsPersec failed: com_error)" in text
    assert "File pool tag objects unknown (pool tags need elevation)" in text


# --- one alert per state change, reminder every 6 h ------------------------------------------------------------


def test_thrash_with_active_pool_sends_one_combined_alert_then_stays_quiet_for_six_hours(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [THRASH])
    run(tmp_path, sink, clock, [THRASH])
    assert len(sink.sent) == 1
    assert "available RAM (free + standby), kernel non-paged pool" in sink.sent[0]
    for _ in range(100):  # the mailbox used to fill with about 100 identical notices
        clock.t += timedelta(minutes=5)
        if clock.t - T0 >= timedelta(hours=6):
            break
        run(tmp_path, sink, clock, [THRASH])
    assert len(sink.sent) == 1


def test_reminder_comes_after_six_hours(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [THRASH])
    run(tmp_path, sink, clock, [THRASH])
    clock.t += timedelta(hours=6) - timedelta(seconds=1)
    run(tmp_path, sink, clock, [THRASH])
    assert len(sink.sent) == 1
    clock.t += timedelta(seconds=1)
    result = run(tmp_path, sink, clock, [THRASH])
    assert len(sink.sent) == 2
    assert set(result.alerted) == {Condition.RAM, Condition.NONPAGED}


def test_low_ram_alone_still_repeats_every_thirty_minutes(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    ram_only = sample(GIB, free_ram=GIB // 2)
    run(tmp_path, sink, clock, [ram_only])
    run(tmp_path, sink, clock, [ram_only])
    clock.t += timedelta(minutes=30)
    run(tmp_path, sink, clock, [ram_only])
    assert len(sink.sent) == 2


def test_pool_growth_by_a_step_is_a_state_change_and_alerts_again(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [THRASH])
    run(tmp_path, sink, clock, [THRASH])
    clock.t += timedelta(minutes=5)
    run(tmp_path, sink, clock, [sample(10 * GIB + GIB - 1, free_ram=GIB // 4)])
    assert len(sink.sent) == 1  # just under one step: unchanged
    clock.t += timedelta(minutes=30)
    run(tmp_path, sink, clock, [sample(11 * GIB, free_ram=GIB // 4)])
    assert len(sink.sent) == 2
    assert "non-paged pool 11.00 GiB" in sink.sent[1]


def test_ram_recovery_while_the_pool_stays_high_is_announced_once(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [THRASH])
    run(tmp_path, sink, clock, [THRASH])
    clock.t += timedelta(minutes=5)
    result = run(tmp_path, sink, clock, [sample(10 * GIB, free_ram=5 * GIB)])
    assert result.recovered == (Condition.RAM,)
    assert sink.sent[-1].startswith("[memory-guard] host: recovered available RAM (free + standby)")
    clock.t += timedelta(minutes=5)
    run(tmp_path, sink, clock, [sample(10 * GIB, free_ram=5 * GIB)])
    assert len(sink.sent) == 2


def test_pool_recovery_announces_and_rearms(tmp_path: Path) -> None:
    sink, clock = Sink(), Clock()
    run(tmp_path, sink, clock, [sample(10 * GIB)])
    run(tmp_path, sink, clock, [sample(10 * GIB)])
    clock.t += timedelta(minutes=5)
    result = run(tmp_path, sink, clock, [sample(GIB)])
    assert result.recovered == (Condition.NONPAGED,)
    assert "recovered kernel non-paged pool" in sink.sent[-1]
    # a new breach after the recovery alerts again once the reminder window has passed
    clock.t += timedelta(hours=7)
    run(tmp_path, sink, clock, [sample(10 * GIB)])
    run(tmp_path, sink, clock, [sample(10 * GIB)])
    assert len(sink.sent) == 3


def test_a_single_pool_sample_does_not_alert(tmp_path: Path) -> None:
    sink = Sink()
    run(tmp_path, sink, Clock(), [sample(10 * GIB)])
    assert sink.sent == []


# --- state file ------------------------------------------------------------------------------------------------


def test_state_written_by_0_4_0_loads_with_a_fresh_pool_row(tmp_path: Path) -> None:
    old = {c: {"consecutive": 3, "active": True, "last_alert": T0.isoformat()} for c in ("free_virtual", "free_ram")}
    (tmp_path / "s.json").write_text(json.dumps(old), encoding="utf-8")
    state = JsonStateStore(tmp_path / "s.json").load()
    assert state.conditions[Condition.RAM].active is True
    assert state.conditions[Condition.NONPAGED].consecutive == 0
    assert state.conditions[Condition.NONPAGED].reference is None


def test_pool_reference_round_trips(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path / "s.json")
    state = store.load()
    state.conditions[Condition.NONPAGED].reference = 10 * GIB
    store.save(state)
    assert store.load().conditions[Condition.NONPAGED].reference == 10 * GIB


def test_malformed_existing_row_is_still_an_explicit_error(tmp_path: Path) -> None:
    (tmp_path / "s.json").write_text(json.dumps({"free_ram": {"consecutive": 1}}), encoding="utf-8")
    with pytest.raises(StateError):
        JsonStateStore(tmp_path / "s.json").load()


# --- counters and pool tags -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [(0, 0), (3200, 3200), ("5239", 5239), (" 7 ", 7), (12.0, 12), (2**32 - 1, 2**32 - 1)]
)
def test_parse_counter_accepts_integers(raw: object, expected: int) -> None:
    assert parse_counter(raw) == expected


@pytest.mark.parametrize("raw", [None, True, "", "abc", "12x", -1, "-5", [1], b"3", 12.5, float("nan")])
def test_parse_counter_rejects_malformed_values(raw: object) -> None:
    with pytest.raises(ProbeError):
        parse_counter(raw)


def table(*rows: tuple[bytes, int, int], count: int | None = None) -> bytes:
    """A SystemPoolTagInformation buffer: header, then (tag, non-paged allocs, non-paged frees) entries."""
    body = b"".join(struct.pack("<4sII4xQIIQ", tag, 0, 0, 0, allocs, frees, 0) for tag, allocs, frees in rows)
    return struct.pack("<I4x", len(rows) if count is None else count) + body


def ok(data: bytes):
    return lambda size: (0, data)


def test_file_tag_objects_is_allocations_minus_frees() -> None:
    data = table((b"Toke", 5, 1), (b"File", 17_000_000, 34_273), (b"IoFE", 9, 9))
    assert file_tag_objects(ok(data)) == 16_965_727


def test_file_tag_objects_grows_the_buffer_on_length_mismatch() -> None:
    calls: list[int] = []

    def query(size: int) -> tuple[int, bytes]:
        calls.append(size)
        if len(calls) == 1:
            return STATUS_INFO_LENGTH_MISMATCH, (9 << 20).to_bytes(8, "little")
        return 0, table((b"File", 4, 1))

    assert file_tag_objects(query) == 3
    assert calls[1] >= 9 << 20


def test_file_tag_objects_runaway_size_request_fails() -> None:
    with pytest.raises(ProbeError, match="larger than"):
        file_tag_objects(lambda size: (STATUS_INFO_LENGTH_MISMATCH, (1 << 40).to_bytes(8, "little")))


def test_file_tag_objects_denied_names_elevation() -> None:
    with pytest.raises(ProbeError, match="elevation"):
        file_tag_objects(lambda size: (STATUS_ACCESS_DENIED, b""))


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"", "shorter than its header"),
        (table((b"File", 1, 0), count=5), "too short"),
        (table((b"File", 1, 5)), "frees exceed"),
        (table((b"Toke", 1, 0)), "not present"),
    ],
)
def test_file_tag_objects_malformed_buffers(data: bytes, match: str) -> None:
    with pytest.raises(ProbeError, match=match):
        file_tag_objects(ok(data))


def test_file_tag_objects_other_status_is_reported() -> None:
    with pytest.raises(ProbeError, match="0xc0000001"):
        file_tag_objects(lambda size: (0xC0000001, b""))


def test_diagnostics_measured_values() -> None:
    d = WindowsPoolDiagnostics(lambda: 4100, ok(table((b"File", 10, 4))))()
    assert d == PoolDiagnostics(Measured(4100), Measured(6))


def test_diagnostics_degrade_independently_and_explicitly() -> None:
    def broken_cim() -> object:
        raise ProbeError("CIM query for PageReadsPersec failed: c0000bb8")

    d = WindowsPoolDiagnostics(broken_cim, lambda size: (STATUS_ACCESS_DENIED, b""))()
    assert d.page_reads_per_s == Unknown("CIM query for PageReadsPersec failed: c0000bb8")
    assert isinstance(d.file_pool_objects, Unknown) and "elevation" in d.file_pool_objects.reason
    mixed = WindowsPoolDiagnostics(lambda: "garbage", ok(table((b"File", 3, 0))))()
    assert isinstance(mixed.page_reads_per_s, Unknown) and "malformed" in mixed.page_reads_per_s.reason
    assert mixed.file_pool_objects == Measured(3)


def test_diagnostics_os_error_becomes_unknown_but_unexpected_errors_stay_visible() -> None:
    def os_fail(size: int) -> tuple[int, bytes]:
        raise OSError("ntdll unavailable")

    d = WindowsPoolDiagnostics(lambda: 1, os_fail)()
    assert isinstance(d.file_pool_objects, Unknown) and "ntdll unavailable" in d.file_pool_objects.reason

    def bug() -> object:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        WindowsPoolDiagnostics(bug, ok(table((b"File", 1, 0))))()
