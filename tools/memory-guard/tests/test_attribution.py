"""Cause attribution: a resident Ollama GPU model, other GPU use, guest cache, and explicit 'cause unknown'."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from memory_guard.adapters.gpu_pdh import PdhGpuMemoryProbe
from memory_guard.adapters.ollama import OllamaPsProbe
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.application.attribution import AttributeCause
from memory_guard.application.check import CheckMemory
from memory_guard.domain.errors import ProbeError
from memory_guard.domain.models import GIB, CauseKind, LoadedModel, MemorySample, Thresholds

T0 = datetime(2026, 11, 25, 22, 0, tzinfo=UTC)
LOW = MemorySample(73 * GIB, 78 * GIB, 6 * GIB, 9 * GIB)
MODEL = LoadedModel("qwen3.5:9b", 9 * GIB, 6 * GIB, T0 + timedelta(minutes=3, seconds=20))


class Clock:
    def now(self) -> datetime:
        return T0


class Gpu:
    def __init__(self, value: int | Exception) -> None:
        self.value = value

    def dedicated_usage(self) -> int:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Models:
    def __init__(self, value: list[LoadedModel] | Exception) -> None:
        self.value = value

    def loaded_models(self) -> list[LoadedModel]:
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def cause(gpu: int | Exception, models: list[LoadedModel] | Exception):
    return AttributeCause(Gpu(gpu), Models(models), Clock(), 4 * GIB)()


def test_gpu_model_resident_names_model_size_and_unload_time() -> None:
    result = cause(12 * GIB, [MODEL])
    assert result.kind is CauseKind.GPU_MODEL
    assert "GPU model resident: qwen3.5:9b (6.00 GiB), unloads ~4 min from now" in result.text
    assert "host GPU dedicated 12.00 GiB" in result.text
    assert "cache" not in result.text


def test_gpu_model_resident_without_expiry() -> None:
    forever = LoadedModel("m", GIB, GIB, T0 + timedelta(days=365))
    assert "no scheduled unload" in cause(5 * GIB, [forever]).text


def test_gpu_model_resident_survives_a_missing_gpu_counter() -> None:
    result = cause(ProbeError("GPU Adapter Memory counter unavailable: x"), [MODEL])
    assert result.kind is CauseKind.GPU_MODEL
    assert "GPU counter unavailable" in result.text


def test_cache_only_when_nothing_is_resident_and_gpu_is_quiet() -> None:
    result = cause(GIB, [])
    assert result.kind is CauseKind.PAGE_CACHE
    assert result.text.startswith("guest page cache")
    assert "inferred, not measured" in result.text


def test_other_gpu_consumer_is_not_blamed_on_cache() -> None:
    result = cause(9 * GIB, [])
    assert result.kind is CauseKind.GPU_OTHER
    assert "another GPU consumer" in result.text


def test_endpoint_down_is_cause_unknown_with_the_reason() -> None:
    result = cause(12 * GIB, ProbeError("Ollama /api/ps unreachable: ConnectError: refused"))
    assert result.kind is CauseKind.UNKNOWN
    assert result.text.startswith("cause unknown: Ollama /api/ps unreachable")
    assert not result.gpu_resident


def test_both_signals_missing_is_cause_unknown_with_both_reasons() -> None:
    result = cause(ProbeError("counter missing"), ProbeError("endpoint down"))
    assert result.kind is CauseKind.UNKNOWN
    assert "endpoint down" in result.text
    assert "counter missing" in result.text


def test_counter_missing_with_no_model_is_unknown_not_cache() -> None:
    result = cause(ProbeError("counter missing"), [])
    assert result.kind is CauseKind.UNKNOWN
    assert "counter missing" in result.text


def _ps_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_probe_parses_api_ps() -> None:
    body = {
        "models": [
            {
                "name": "qwen3.5:9b",
                "size": 9 * GIB,
                "size_vram": 6 * GIB,
                "expires_at": "2026-11-25T19:03:20.123456789-03:00",
            }
        ]
    }
    probe = OllamaPsProbe("https://ollama.example/", 5, _ps_client(lambda r: httpx.Response(200, json=body)))
    (model,) = probe.loaded_models()
    assert (model.name, model.size_vram) == ("qwen3.5:9b", 6 * GIB)
    assert model.expires_at.utcoffset() == timedelta(hours=-3)


def test_ollama_probe_requests_the_ps_path() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"models": []})

    assert OllamaPsProbe("https://ollama.example/", 5, _ps_client(handler)).loaded_models() == []
    assert seen == ["https://ollama.example/api/ps"]


def test_ollama_probe_unset_url_is_an_explicit_failure() -> None:
    with pytest.raises(ProbeError, match="MEMORY_GUARD_OLLAMA_URL is not set"):
        OllamaPsProbe(None, 5).loaded_models()


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(503),
        lambda r: httpx.Response(200, json={"models": [{"name": "x"}]}),
        lambda r: httpx.Response(200, content=b"not json"),
    ],
    ids=["http-error", "missing-required-field", "malformed"],
)
def test_ollama_probe_bad_answers_raise_probe_error(handler) -> None:
    with pytest.raises(ProbeError, match="Ollama /api/ps"):
        OllamaPsProbe("https://ollama.example", 5, _ps_client(handler)).loaded_models()


def test_ollama_probe_connection_failure_raises_probe_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProbeError, match="unreachable"):
        OllamaPsProbe("https://ollama.example", 5, _ps_client(handler)).loaded_models()


@pytest.mark.skipif(sys.platform != "win32", reason="PDH is Windows only")
def test_pdh_probe_reads_the_live_counter_or_fails_explicitly() -> None:
    try:
        value = PdhGpuMemoryProbe().dedicated_usage()
    except ProbeError as exc:
        assert "GPU Adapter Memory" in str(exc)
    else:
        assert value >= 0


class Procs:
    def top_by_private_bytes(self, limit: int):
        return [], 0


class Sink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class Reclaimer:
    """Models the policy guards the real one owns: enabled and the sustained-sample count."""

    def __init__(self, enabled: bool = True, samples: int = 2) -> None:
        self.calls, self.enabled, self.samples = 0, enabled, samples

    def eligible(self, consecutive_low: int) -> bool:
        return self.enabled and consecutive_low >= self.samples

    def __call__(self, sample, consecutive_low):
        if self.eligible(consecutive_low):  # the real reclaimer declines through the same guards
            self.calls += 1
        return None

    def last_summary(self):
        return None


class Probe:
    def sample(self) -> MemorySample:
        return LOW


def run_guard(tmp_path: Path, gpu, models, reclaimer: Reclaimer | None = None, probe=None, runs: int = 2):
    sink, reclaimer = Sink(), reclaimer or Reclaimer()
    guard = CheckMemory(
        probe or Probe(),
        Procs(),
        sink,
        JsonStateStore(tmp_path / "s.json"),
        Clock(),
        Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30)),
        "host",
        10,
        reclaimer,
        AttributeCause(Gpu(gpu), Models(models), Clock(), 4 * GIB),
    )
    for _ in range(runs):
        guard()
    return sink, reclaimer


def test_alert_names_the_resident_model_and_no_cache_drop_is_attempted(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, [MODEL])
    (text,) = sink.sent
    assert "cause: GPU model resident: qwen3.5:9b" in text
    assert "WSL cache drop skipped" in text
    assert reclaimer.calls == 0


def test_skipped_note_is_absent_when_the_drop_was_never_eligible(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, [MODEL], Reclaimer(enabled=False))
    assert "cause: GPU model resident" in sink.sent[0]
    assert "skipped" not in sink.sent[0]
    assert reclaimer.calls == 0


def test_cache_only_alert_still_drops_the_cache(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, GIB, [])
    assert "cause: guest page cache is the candidate" in sink.sent[0]
    assert reclaimer.calls == 1  # run 1 is not sustained yet, run 2 is


def test_endpoint_down_alert_says_cause_unknown_and_still_drops(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, ProbeError("Ollama /api/ps unreachable: ConnectError"))
    assert "cause unknown: Ollama /api/ps unreachable" in sink.sent[0]
    assert "cause: cause unknown" not in sink.sent[0]
    assert reclaimer.calls == 1


def test_counter_missing_alert_says_cause_unknown(tmp_path: Path) -> None:
    sink, _ = run_guard(tmp_path, ProbeError("GPU Adapter Memory counter unavailable: gone"), [])
    assert "cause unknown: no Ollama model resident, GPU Adapter Memory counter unavailable" in sink.sent[0]


def test_unexpected_probe_exception_still_sends_the_alert_as_cause_unknown(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, RuntimeError("boom"))
    assert "cause unknown: attribution failed: RuntimeError: boom" in sink.sent[0]
    assert reclaimer.calls == 1


def test_naive_expiry_is_an_explicit_unknown_not_a_crash() -> None:
    naive = LoadedModel("m", GIB, GIB, datetime(2026, 11, 25, 22, 5))
    result = cause(5 * GIB, [naive])
    assert result.kind is CauseKind.UNKNOWN
    assert "attribution failed: TypeError" in result.text


def test_cpu_resident_model_is_not_blamed_on_the_gpu_or_the_cache() -> None:
    result = cause(GIB, [LoadedModel("small", 3 * GIB, 0, T0 + timedelta(minutes=2))])
    assert result.kind is CauseKind.CPU_MODEL
    assert "resident in RAM, not on the GPU: small (3.00 GiB)" in result.text
    assert not result.gpu_resident


class RamOnlyProbe:
    def sample(self) -> MemorySample:
        return MemorySample(10 * GIB, 78 * GIB, GIB // 2, 9 * GIB)  # plenty of commit, little physical RAM


def test_ram_only_breach_is_not_attributed_to_the_gpu(tmp_path: Path) -> None:
    sink, _ = run_guard(tmp_path, 12 * GIB, [MODEL], probe=RamOnlyProbe())
    assert "free RAM" in sink.sent[0]
    assert "cause" not in sink.sent[0]


def test_no_attribution_work_before_the_condition_is_sustained(tmp_path: Path) -> None:
    class Counting(Models):
        calls = 0

        def loaded_models(self):
            Counting.calls += 1
            return super().loaded_models()

    guard = CheckMemory(
        Probe(),
        Procs(),
        Sink(),
        JsonStateStore(tmp_path / "s.json"),
        Clock(),
        Thresholds(8 * GIB, GIB, 2, timedelta(minutes=30)),
        "host",
        10,
        Reclaimer(),
        AttributeCause(Gpu(GIB), Counting([]), Clock(), 4 * GIB),
    )
    guard()
    assert Counting.calls == 0


def test_http_status_error_message_keeps_the_host_out() -> None:
    client = _ps_client(lambda r: httpx.Response(503))
    with pytest.raises(ProbeError) as info:
        OllamaPsProbe("https://private-host.example", 5, client).loaded_models()
    assert "HTTP 503" in str(info.value)
    assert "private-host" not in str(info.value)


def test_invalid_url_is_an_explicit_probe_error() -> None:
    with pytest.raises(ProbeError, match="unreachable"):
        OllamaPsProbe("http://[bad", 5).loaded_models()


class FakePdh:
    """A stand-in for the win32pdh module: records that the query is closed."""

    PDH_FMT_LARGE = 1024

    class error(Exception):
        pass

    def __init__(self, values=None, fail: bool = False) -> None:
        self.values, self.fail, self.closed = values, fail, False

    def OpenQuery(self):
        return "q"

    def AddEnglishCounter(self, query, path):
        assert path == r"\GPU Adapter Memory(*)\Dedicated Usage"
        if self.fail:
            raise self.error("no such counter")
        return "h"

    def CollectQueryData(self, query):
        return None

    def GetFormattedCounterArray(self, handle, fmt):
        assert fmt == self.PDH_FMT_LARGE
        return self.values

    def CloseQuery(self, query):
        self.closed = True


def pdh(monkeypatch: pytest.MonkeyPatch, fake: FakePdh) -> PdhGpuMemoryProbe:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32pdh", fake)
    return PdhGpuMemoryProbe()


def test_pdh_sums_adapters_and_closes_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePdh({"a": 3 * GIB, "b": 5 * GIB})
    assert pdh(monkeypatch, fake).dedicated_usage() == 8 * GIB
    assert fake.closed


def test_pdh_no_instances_is_an_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePdh({})
    with pytest.raises(ProbeError, match="no adapter instances"):
        pdh(monkeypatch, fake).dedicated_usage()
    assert fake.closed


def test_pdh_counter_error_is_an_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePdh(fail=True)
    with pytest.raises(ProbeError, match="GPU Adapter Memory counter unavailable"):
        pdh(monkeypatch, fake).dedicated_usage()
    assert fake.closed


def test_pdh_missing_pywin32_is_an_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "win32pdh", None)  # makes the import raise ImportError
    with pytest.raises(ProbeError, match="pywin32 is not installed"):
        PdhGpuMemoryProbe().dedicated_usage()
