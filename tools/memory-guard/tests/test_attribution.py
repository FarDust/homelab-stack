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
MODEL = LoadedModel("qwen3.5:9b", 6 * GIB, T0 + timedelta(minutes=3, seconds=20))


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
    forever = LoadedModel("m", GIB, T0 + timedelta(days=365))
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
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, sample, consecutive_low):
        self.calls += 1
        return None

    def last_summary(self):
        return None


class Probe:
    def sample(self) -> MemorySample:
        return LOW


def run_guard(tmp_path: Path, gpu, models) -> tuple[Sink, Reclaimer]:
    sink, reclaimer = Sink(), Reclaimer()
    guard = CheckMemory(
        Probe(),
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
    guard()
    guard()
    return sink, reclaimer


def test_alert_names_the_resident_model_and_no_cache_drop_is_attempted(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, [MODEL])
    (text,) = sink.sent
    assert "cause: GPU model resident: qwen3.5:9b" in text
    assert "WSL cache drop skipped" in text
    assert reclaimer.calls == 0


def test_cache_only_alert_still_drops_the_cache(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, GIB, [])
    assert "cause: guest page cache" in sink.sent[0]
    assert reclaimer.calls >= 1


def test_endpoint_down_alert_says_cause_unknown_and_still_drops(tmp_path: Path) -> None:
    sink, reclaimer = run_guard(tmp_path, 12 * GIB, ProbeError("Ollama /api/ps unreachable: ConnectError: refused"))
    assert "cause unknown: Ollama /api/ps unreachable" in sink.sent[0]
    assert reclaimer.calls >= 1


def test_counter_missing_alert_says_cause_unknown(tmp_path: Path) -> None:
    sink, _ = run_guard(tmp_path, ProbeError("GPU Adapter Memory counter unavailable: gone"), [])
    assert "cause unknown: no Ollama model resident, GPU Adapter Memory counter unavailable" in sink.sent[0]
