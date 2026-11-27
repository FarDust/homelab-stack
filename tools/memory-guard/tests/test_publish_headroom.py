"""publish-headroom through its ports: feature flag, never-start-WSL, exact textfile, stdin-only content, failures."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_guard import cli
from memory_guard.adapters.wsl import WslTextfileWriter
from memory_guard.application.publish_headroom import PublishHeadroom
from memory_guard.domain.errors import ProbeError, PublishError
from memory_guard.domain.headroom import TEXTFILE_PATH, HeadroomReading, PublishStatus, render_textfile
from memory_guard.domain.models import GIB, MemorySample

T0 = datetime(2026, 11, 27, 15, 0, 0, 250000, tzinfo=UTC)
SAMPLE = MemorySample(60 * GIB, 78 * GIB, 8 * GIB, GIB, 64 * GIB)  # 18 GiB headroom


class FakeProbe:
    def __init__(self, sample: MemorySample) -> None:
        self.sample_value, self.calls = sample, 0

    def sample(self) -> MemorySample:
        self.calls += 1
        return self.sample_value


class FakeDistro:
    def __init__(self, running: bool) -> None:
        self.running, self.calls = running, 0

    def is_running(self) -> bool:
        self.calls += 1
        return self.running


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.written: list[str] = []
        self.fail = fail

    def write(self, content: str) -> None:
        if self.fail:
            raise PublishError("textfile write exited 1: No such file or directory")
        self.written.append(content)


class Clock:
    def now(self) -> datetime:
        return T0


def make(enabled: bool = True, running: bool = True, sample: MemorySample = SAMPLE, writer: FakeWriter | None = None):
    probe, distro, writer = FakeProbe(sample), FakeDistro(running), writer or FakeWriter()
    return PublishHeadroom(enabled, probe, distro, writer, Clock(), "gabriel-pc"), probe, distro, writer


EXPECTED = (
    "# HELP memory_guard_commit_headroom_bytes Windows free virtual memory (commit limit minus commit charge) in bytes.\n"
    "# TYPE memory_guard_commit_headroom_bytes gauge\n"
    'memory_guard_commit_headroom_bytes{host="gabriel-pc"} 19327352832\n'
    "# HELP memory_guard_commit_sample_timestamp_seconds Unix time when memory-guard sampled the commit headroom.\n"
    "# TYPE memory_guard_commit_sample_timestamp_seconds gauge\n"
    'memory_guard_commit_sample_timestamp_seconds{host="gabriel-pc"} 1795791600.250\n'
)


def test_disabled_flag_touches_nothing() -> None:
    use_case, probe, distro, writer = make(enabled=False)
    assert use_case().status is PublishStatus.DISABLED
    assert (probe.calls, distro.calls, writer.written) == (0, 0, [])


def test_distro_not_running_does_not_write() -> None:
    use_case, probe, distro, writer = make(running=False)
    assert use_case().status is PublishStatus.DISTRO_NOT_RUNNING
    assert distro.calls == 1 and writer.written == [] and probe.calls == 0


def test_published_text_is_exact() -> None:
    use_case, _, _, writer = make()
    outcome = use_case()
    assert outcome.status is PublishStatus.PUBLISHED
    assert outcome.reading == HeadroomReading(18 * GIB, T0.timestamp())
    assert writer.written == [EXPECTED]
    assert EXPECTED.endswith("\n")


def test_writer_failure_propagates() -> None:
    use_case, *_ = make(writer=FakeWriter(fail=True))
    with pytest.raises(PublishError, match="exited 1"):
        use_case()


def test_negative_headroom_is_explicit() -> None:
    use_case, _, _, writer = make(sample=MemorySample(80 * GIB, 78 * GIB, GIB, GIB, 64 * GIB))
    with pytest.raises(ProbeError, match="negative"):
        use_case()
    assert writer.written == []


@pytest.mark.parametrize("value", [1.5, "12", True, None])
def test_malformed_headroom_is_explicit(value: object) -> None:
    with pytest.raises(ProbeError, match="integer"):
        HeadroomReading(value, T0.timestamp())  # type: ignore[arg-type]


@pytest.mark.parametrize("ts", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_timestamp_is_explicit(ts: float) -> None:
    with pytest.raises(ProbeError, match="timestamp"):
        HeadroomReading(GIB, ts)


def test_host_label_must_be_plain_token() -> None:
    with pytest.raises(ValueError, match="host label"):
        render_textfile(HeadroomReading(GIB, T0.timestamp()), 'x"}\nevil 1')


class RecordingRunner:
    def __init__(self, returncode: int = 0, stderr: bytes = b"", exc: Exception | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.returncode, self.stderr, self.exc = returncode, stderr, exc

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


def test_writer_sends_content_on_stdin_not_argv() -> None:
    runner = RecordingRunner()
    WslTextfileWriter("Ubuntu", TEXTFILE_PATH, 30, runner).write(EXPECTED)
    [(argv, kw)] = runner.calls
    assert argv[:8] == ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", "sh", "-c"]
    assert argv[8] == (f"cat > {TEXTFILE_PATH}.tmp && mv {TEXTFILE_PATH}.tmp {TEXTFILE_PATH}")
    assert not any("memory_guard_commit_headroom_bytes" in a for a in argv)
    assert kw["input"] == EXPECTED.encode("utf-8") and kw["timeout"] == 30 and kw["check"] is False


def test_writer_nonzero_exit_and_timeout_are_publish_errors() -> None:
    with pytest.raises(PublishError, match="exited 2: mv: cannot move"):
        WslTextfileWriter("Ubuntu", TEXTFILE_PATH, 30, RecordingRunner(2, b"mv: cannot move")).write("x\n")
    timeout = RecordingRunner(exc=subprocess.TimeoutExpired("wsl.exe", 30))
    with pytest.raises(PublishError, match="timed out after 30s"):
        WslTextfileWriter("Ubuntu", TEXTFILE_PATH, 30, timeout).write("x\n")


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, enabled: str) -> None:
    monkeypatch.setenv("MEMORY_GUARD_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GUARD_ALERT_COMMAND", "echo|{message}")
    monkeypatch.setenv("MEMORY_GUARD_HEADROOM_PUBLISH_ENABLED", enabled)


def test_cli_disabled_exits_0_without_wsl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, tmp_path, "false")
    result = CliRunner().invoke(cli.app, ["publish-headroom"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "disabled"


def test_cli_writer_failure_exits_1_with_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, tmp_path, "true")
    use_case, *_ = make(writer=FakeWriter(fail=True))
    monkeypatch.setattr(cli, "build_publish_headroom", lambda settings: use_case)
    result = CliRunner().invoke(cli.app, ["publish-headroom"])
    assert result.exit_code == 1
    assert "publish-headroom failed: PublishError: textfile write exited 1" in result.stderr


def test_cli_not_running_exits_0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, tmp_path, "true")
    use_case, *_ = make(running=False)
    monkeypatch.setattr(cli, "build_publish_headroom", lambda settings: use_case)
    result = CliRunner().invoke(cli.app, ["publish-headroom"])
    assert result.exit_code == 0
    assert "not running, not published" in json.loads(result.stdout)["message"]


def test_cli_published_prints_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, tmp_path, "true")
    use_case, *_ = make()
    monkeypatch.setattr(cli, "build_publish_headroom", lambda settings: use_case)
    result = CliRunner().invoke(cli.app, ["publish-headroom"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["commit_headroom_bytes"] == 18 * GIB
