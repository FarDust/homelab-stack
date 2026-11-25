"""Tests through the public API: the use case with fakes, the adapters against their ports, the CLI wiring."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_guard.adapters.command_alert import CommandAlertSink
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.application.check import CheckMemory
from memory_guard.cli import app
from memory_guard.domain.errors import AlertError, ProbeError, StateError
from memory_guard.domain.models import GIB, Condition, MemorySample, ProcessUsage, Thresholds

T0 = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
LOW = MemorySample(70 * GIB, 78 * GIB - 1, 5 * GIB, 9 * GIB)  # free virtual just under 8 GiB
LOW_RAM = MemorySample(10 * GIB, 78 * GIB, GIB // 2, 9 * GIB)
OK = MemorySample(30 * GIB, 78 * GIB, 8 * GIB, 9 * GIB)


class FakeProbe:
    def __init__(self, *samples: MemorySample | Exception) -> None:
        self.samples = list(samples)

    def sample(self) -> MemorySample:
        item = self.samples.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeProcs:
    def top_by_private_bytes(self, limit: int):
        return [ProcessUsage(i, f"p{i}.exe", (20 - i) * GIB) for i in range(limit)], 2


class FakeSink:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        if self.fail:
            raise AlertError("down")
        self.sent.append(text)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        return self.t


def make(tmp_path: Path, probe: FakeProbe, sink: FakeSink, clock: Clock) -> CheckMemory:
    th = Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30))
    return CheckMemory(probe, FakeProcs(), sink, JsonStateStore(tmp_path / "s.json"), clock, th, "host")


def test_one_low_sample_does_not_alert(tmp_path: Path) -> None:
    sink = FakeSink()
    make(tmp_path, FakeProbe(LOW, OK), sink, Clock())()
    assert sink.sent == []


def test_two_consecutive_samples_alert_with_top_ten_and_pool(tmp_path: Path) -> None:
    sink, clock = FakeSink(), Clock()
    guard = make(tmp_path, FakeProbe(LOW, LOW), sink, clock)
    guard()
    result = guard()
    assert result.alerted == (Condition.VIRTUAL,)
    assert len(sink.sent) == 1
    text = sink.sent[0]
    assert "non-paged pool 9.00 GiB" in text and text.count(".exe") == 10 and "2 unreadable" in text


def test_rate_limit_then_realert_then_recovery(tmp_path: Path) -> None:
    sink, clock = FakeSink(), Clock()
    guard = make(tmp_path, FakeProbe(LOW, LOW, LOW, LOW, OK), sink, clock)
    guard()
    guard()
    clock.t += timedelta(minutes=5)
    guard()
    assert len(sink.sent) == 1  # within 30 minutes
    clock.t += timedelta(minutes=30)
    guard()
    assert len(sink.sent) == 2
    clock.t += timedelta(minutes=5)
    result = guard()
    assert result.recovered == (Condition.VIRTUAL,)
    assert "recovered" in sink.sent[-1]


def test_ram_condition_is_independent(tmp_path: Path) -> None:
    sink = FakeSink()
    guard = make(tmp_path, FakeProbe(LOW_RAM, LOW_RAM), sink, Clock())
    guard()
    assert guard().alerted == (Condition.RAM,)


def test_alert_failure_propagates_and_is_retried(tmp_path: Path) -> None:
    clock = Clock()
    bad = make(tmp_path, FakeProbe(LOW, LOW), FakeSink(fail=True), clock)
    bad()
    with pytest.raises(AlertError):
        bad()
    good = FakeSink()
    make(tmp_path, FakeProbe(LOW), good, clock)()
    assert len(good.sent) == 1  # not marked alerted by the failed attempt


def test_probe_failure_propagates(tmp_path: Path) -> None:
    with pytest.raises(ProbeError):
        make(tmp_path, FakeProbe(ProbeError("no counter")), FakeSink(), Clock())()


def test_malformed_state_is_explicit(tmp_path: Path) -> None:
    (tmp_path / "s.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError):
        JsonStateStore(tmp_path / "s.json").load()


def test_command_sink_requires_placeholder_and_receipt() -> None:
    with pytest.raises(AlertError):
        CommandAlertSink(["x"], 1, "delivered")

    def run_ok(argv, **kw):
        assert argv == ["bridge", "hello"]
        return subprocess.CompletedProcess(argv, 0, "delivered abc", "")

    CommandAlertSink(["bridge", "{message}"], 1, "delivered", run_ok).send("hello")

    def run_silent(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(AlertError):
        CommandAlertSink(["bridge", "{message}"], 1, "delivered", run_silent).send("hello")

    def run_fail(argv, **kw):
        return subprocess.CompletedProcess(argv, 3, "", "boom")

    with pytest.raises(AlertError, match="exited 3"):
        CommandAlertSink(["bridge", "{message}"], 1, "delivered", run_fail).send("hello")


def test_cli_missing_alert_command_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_GUARD_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("MEMORY_GUARD_ALERT_COMMAND", raising=False)
    assert CliRunner().invoke(app, ["check"]).exit_code == 2


def test_cli_alert_path_failure_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_GUARD_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GUARD_ALERT_COMMAND", "definitely-not-a-command-xyz|{message}")
    monkeypatch.setenv("MEMORY_GUARD_SAMPLES", "1")
    result = CliRunner().invoke(app, ["check", "--min-free-virtual-gb", "100000"])
    assert result.exit_code == 1
