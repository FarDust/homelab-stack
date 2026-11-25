"""Opt-in WSL cache drop: guards, recorded numbers, explicit failures, and the order against the alert path."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_guard.adapters.reclaim_log import JsonlReclaimLog
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.adapters.windows_probe import PsutilVmmemProbe
from memory_guard.adapters.wsl import DROP_SCRIPT, WslCli
from memory_guard.application.check import CheckMemory
from memory_guard.application.reclaim import ReclaimWslCache
from memory_guard.cli import app
from memory_guard.domain.errors import AlertError, GuardError, ProbeError, ReclaimError, StateError
from memory_guard.domain.models import GIB, MemorySample, ReclaimPolicy, ReclaimRecord, ReclaimSnapshot, Thresholds

T0 = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
LOW = MemorySample(73 * GIB, 78 * GIB, 6 * GIB, 9 * GIB)  # 5 GiB free virtual
AFTER = MemorySample(68 * GIB, 78 * GIB, 10 * GIB, 9 * GIB)  # 10 GiB free virtual
POLICY = ReclaimPolicy(True, 2, timedelta(minutes=10), 6, 4.0)


class Probe:
    """Low memory, except for the one reading taken right after a cache drop (or a forced override)."""

    def __init__(self) -> None:
        self.wsl: Wsl | None = None
        self.seen = 0
        self.override: MemorySample | None = None

    def sample(self) -> MemorySample:
        if self.override:
            return self.override
        if self.wsl and self.wsl.drops > self.seen:
            self.seen = self.wsl.drops
            return AFTER
        return LOW


class Procs:
    def top_by_private_bytes(self, limit: int):
        return [], 0


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        return self.t


class Wsl:
    def __init__(self, events: list[str], running: bool = True, error: Exception | None = None) -> None:
        self.events, self.running, self.error = events, running, error
        self.drops = 0

    def is_running(self) -> bool:
        return self.running

    def drop_cache(self) -> None:
        self.events.append("drop")
        self.drops += 1
        if self.error:
            raise self.error


class Vmmem:
    def __init__(self, *values: int | Exception) -> None:
        self.values = list(values)

    def private_bytes(self) -> int:
        item = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(item, Exception):
            raise item
        return item


class Sink:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events, self.sent, self.fail = events, [], fail

    def send(self, text: str) -> None:
        self.events.append("send")
        if self.fail:
            raise AlertError("bridge down")
        self.sent.append(text)


class Rig:
    def __init__(
        self,
        tmp_path: Path,
        wsl_error: Exception | None = None,
        running: bool = True,
        vmmem=None,
        sink_fail=False,
        policy=POLICY,
    ):
        self.events: list[str] = []
        self.clock, self.sleeps = Clock(), []
        self.wsl = Wsl(self.events, running, wsl_error)
        self.log = JsonlReclaimLog(tmp_path / "reclaim.jsonl")
        self.sink = Sink(self.events, sink_fail)
        self.probe = Probe()
        self.probe.wsl = self.wsl
        vm = vmmem or Vmmem(24 * GIB, 20 * GIB)
        reclaimer = ReclaimWslCache(self.wsl, vm, self.probe, self.log, self.clock, policy, self.sleeps.append)
        th = Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30))
        self.guard = CheckMemory(
            self.probe, Procs(), self.sink, JsonStateStore(tmp_path / "s.json"), self.clock, th, "host", 10, reclaimer
        )

    def second_low_run(self):
        self.guard()
        return self.guard()


def test_drop_runs_before_alert_and_records_numbers(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    result = rig.second_low_run()
    assert rig.events == ["drop", "send"]  # the remediation never waits on the alert path
    assert result.reclaim is not None
    text = rig.sink.sent[0]
    assert "free virtual 5.00 GiB -> 10.00 GiB" in text and "vmmemWSL 24.00 GiB -> 20.00 GiB" in text
    assert "free RAM 6.00 GiB -> 10.00 GiB" in text
    [row] = rig.log.recent(T0 - timedelta(hours=1))
    assert row.ok and row.after == ReclaimSnapshot(10 * GIB, 10 * GIB, 20 * GIB)


def test_first_low_sample_does_not_drop(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.guard()
    assert rig.wsl.drops == 0


def test_stopped_distro_is_never_started(tmp_path: Path) -> None:
    rig = Rig(tmp_path, running=False)
    result = rig.second_low_run()
    assert rig.wsl.drops == 0 and result.reclaim is None
    assert rig.log.recent(T0 - timedelta(hours=1)) == []


def test_kill_switch_disables_the_drop(tmp_path: Path) -> None:
    rig = Rig(tmp_path, policy=ReclaimPolicy(False, 2, timedelta(minutes=10), 6, 4.0))
    rig.second_low_run()
    assert rig.wsl.drops == 0


def test_min_interval_between_drops(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.second_low_run()
    rig.clock.t += timedelta(minutes=5)
    rig.guard()
    assert rig.wsl.drops == 1
    rig.clock.t += timedelta(minutes=6)  # 11 minutes after the first drop
    rig.guard()
    assert rig.wsl.drops == 2


def test_max_six_per_hour(tmp_path: Path) -> None:
    policy = ReclaimPolicy(True, 2, timedelta(minutes=1), 6, 4.0)
    rig = Rig(tmp_path, policy=policy)
    rig.guard()
    for _ in range(8):
        rig.guard()
        rig.clock.t += timedelta(minutes=2)
    assert rig.wsl.drops == 6


def test_timeout_is_explicit_logged_and_alert_still_goes_out(tmp_path: Path) -> None:
    rig = Rig(tmp_path, wsl_error=ReclaimError("WSL cache drop timed out after 60s"))
    rig.guard()
    with pytest.raises(ReclaimError, match="timed out"):
        rig.guard()
    assert "WSL cache drop failed: WSL cache drop timed out" in rig.sink.sent[0]
    [row] = rig.log.recent(T0 - timedelta(hours=1))
    assert not row.ok and row.after is None and "timed out" in (row.error or "")
    rig.clock.t += timedelta(minutes=1)
    rig.guard()
    assert rig.wsl.drops == 1  # a failed attempt counts toward the rate limit


def test_missing_vmmem_counter_is_explicit_and_nothing_runs(tmp_path: Path) -> None:
    rig = Rig(tmp_path, vmmem=Vmmem(ProbeError("vmmemWSL process not found")))
    rig.guard()
    with pytest.raises(ProbeError):
        rig.guard()
    assert rig.wsl.drops == 0


def test_reclaim_and_alert_failures_are_both_reported(tmp_path: Path) -> None:
    rig = Rig(tmp_path, wsl_error=ReclaimError("exit 1"), sink_fail=True)
    rig.guard()
    with pytest.raises(GuardError, match=r"exit 1.*alert path failed"):
        rig.guard()


def test_settle_polls_the_counters_until_the_bound(tmp_path: Path) -> None:
    rig = Rig(tmp_path, vmmem=Vmmem(24 * GIB))  # vmmemWSL never shrinks
    rig.second_low_run()
    assert rig.sleeps == [2.0, 2.0]  # bounded by settle_s = 4


def test_recovery_message_carries_the_last_drop(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.second_low_run()
    rig.probe.override = AFTER
    rig.clock.t += timedelta(minutes=5)
    rig.guard()
    assert "recovered" in rig.sink.sent[-1] and "WSL cache drop at" in rig.sink.sent[-1]


def test_malformed_log_is_explicit(tmp_path: Path) -> None:
    (tmp_path / "reclaim.jsonl").write_text("{nope\n", encoding="utf-8")
    with pytest.raises(StateError):
        JsonlReclaimLog(tmp_path / "reclaim.jsonl").recent(T0)


def test_log_is_trimmed(tmp_path: Path) -> None:
    log = JsonlReclaimLog(tmp_path / "r.jsonl")
    rec = ReclaimRecord(T0, False, ReclaimSnapshot(1, 2, 3), None, "x")
    for _ in range(1001):
        log.append(rec)
    assert len((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()) == 500


def _cp(rc: int, out: bytes = b"", err: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], rc, out, err)


def test_wsl_cli_lists_running_distros_and_never_drops() -> None:
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(argv)
        return _cp(0, "Ubuntu\r\nRecovery\r\n".encode("utf-16-le"))

    assert WslCli("Ubuntu", 60, run).is_running() is True
    assert WslCli("Other", 60, run).is_running() is False
    assert all("-d" not in c for c in calls)  # listing never targets (and so never starts) a distro
    assert WslCli("Ubuntu", 60, lambda *a, **k: _cp(0, b"")).is_running() is False


def test_wsl_cli_drop_command_and_failures() -> None:
    seen: dict[str, object] = {}

    def ok(argv, **kw):
        seen.update(argv=argv, timeout=kw["timeout"])
        return _cp(0)

    WslCli("Ubuntu", 60, ok).drop_cache()
    assert seen["argv"] == ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "sh", "-c", DROP_SCRIPT]
    assert seen["timeout"] == 60

    with pytest.raises(ReclaimError, match="exited 5: denied"):
        WslCli("Ubuntu", 60, lambda *a, **k: _cp(5, b"", b"denied")).drop_cache()

    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    with pytest.raises(ReclaimError, match="timed out after 60s"):
        WslCli("Ubuntu", 60, hang).drop_cache()

    def missing(argv, **kw):
        raise FileNotFoundError("wsl.exe")

    with pytest.raises(ReclaimError, match=r"could not run wsl\.exe"):
        WslCli("Ubuntu", 60, missing).is_running()


def test_vmmem_probe_missing_process_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("memory_guard.adapters.windows_probe.psutil.process_iter", lambda attrs: [])
    with pytest.raises(ProbeError, match="vmmemWSL"):
        PsutilVmmemProbe().private_bytes()


def test_cli_kill_switch_env_disables_the_drop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_GUARD_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GUARD_ALERT_COMMAND", "definitely-not-a-command-xyz|{message}")
    monkeypatch.setenv("MEMORY_GUARD_RECLAIM_ENABLED", "false")
    monkeypatch.setenv("MEMORY_GUARD_SAMPLES", "1")
    monkeypatch.setenv("MEMORY_GUARD_RECLAIM_SAMPLES", "1")
    result = CliRunner().invoke(app, ["check", "--min-free-virtual-gb", "100000"])
    assert result.exit_code == 1  # the alert path fails; no reclaim log was written
    assert not (tmp_path / "reclaim.jsonl").exists()


def test_eligible_follows_the_policy_guards(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    reclaimer = rig.guard._reclaimer
    assert not reclaimer.eligible(1)  # not sustained
    assert reclaimer.eligible(2)
    rig.second_low_run()
    assert not reclaimer.eligible(2)  # a drop just ran: the minimum interval holds
    (tmp_path / "off").mkdir()
    off = Rig(tmp_path / "off", policy=ReclaimPolicy(False, 2, timedelta(minutes=10), 6, 4.0))
    assert not off.guard._reclaimer.eligible(5)


def test_resident_gpu_model_blocks_the_real_reclaimer_end_to_end(tmp_path: Path) -> None:
    from memory_guard.application.attribution import AttributeCause
    from memory_guard.domain.models import LoadedModel

    class Gpu:
        def dedicated_usage(self) -> int:
            return 12 * GIB

    class Ollama:
        def loaded_models(self):
            return [LoadedModel("qwen3.5:9b", 9 * GIB, 6 * GIB, T0 + timedelta(minutes=4))]

    rig = Rig(tmp_path)
    rig.guard._attributor = AttributeCause(Gpu(), Ollama(), rig.clock, 4 * GIB)
    rig.second_low_run()
    assert rig.wsl.drops == 0
    assert "GPU model resident: qwen3.5:9b" in rig.sink.sent[0]
    assert "WSL cache drop skipped" in rig.sink.sent[0]
