"""Behaviour of the feed through its public API with fake runners: no network, no gh, no ssh."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_prs_feed.adapters.gh_cli import GhCliSource
from open_prs_feed.adapters.process import RunResult
from open_prs_feed.adapters.sinks import LocalAtomicSink, SshAtomicSink
from open_prs_feed.application.publish import CollectSnapshot, PublishOpenPrs
from open_prs_feed.cli import app
from open_prs_feed.config import Settings
from open_prs_feed.domain.errors import (
    EmptySnapshotError,
    MalformedSourceError,
    SinkError,
    SourceUnavailableError,
    TruncatedSourceError,
)

NOW = datetime(2026, 11, 25, 13, 40, tzinfo=UTC)
SHA_A = "3c9b623003bb2c40ca3d3c6d44e2bd57ff8bc079"
SHA_B = "e5cf5ce7" + "0" * 32


class FixedClock:
    def now(self) -> datetime:
        return NOW


def gh_row(number: int, sha: str = SHA_A, branch: str = "feat/x", updated: str = "2026-11-25T13:29:55Z") -> dict:
    return {"number": number, "headRefOid": sha, "headRefName": branch, "updatedAt": updated}


class FakeRunner:
    """Answers `gh pr list --repo <r>` from a table; records ssh writes."""

    def __init__(self, answers: dict[str, Callable[[], RunResult] | RunResult]) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], bytes | None]] = []

    def run(self, argv: Sequence[str], stdin: bytes | None, timeout_s: float) -> RunResult:
        self.calls.append((list(argv), stdin))
        if "--repo" in argv:
            ans = self.answers[argv[list(argv).index("--repo") + 1]]
            return ans() if callable(ans) else ans
        return self.answers["ssh"]() if callable(self.answers["ssh"]) else self.answers["ssh"]


def ok(rows: list[dict]) -> RunResult:
    return RunResult(0, json.dumps(rows).encode(), b"")


def source(runner: FakeRunner, limit: int = 50) -> GhCliSource:
    return GhCliSource(runner, ["gh"], limit, 5.0)


def publish(tmp_path: Path, runner: FakeRunner, repos: Sequence[str], allow_empty: bool = False) -> PublishOpenPrs:
    collect = CollectSnapshot(source(runner), FixedClock(), repos, allow_empty)
    return PublishOpenPrs(collect, LocalAtomicSink(tmp_path), "open-prs.json", "open-prs.detail.json")


def seed_last_good(tmp_path: Path) -> None:
    (tmp_path / "open-prs.json").write_text("[201]\n", encoding="utf-8")
    (tmp_path / "open-prs.detail.json").write_text("{}\n", encoding="utf-8")


def assert_last_good_kept(tmp_path: Path) -> None:
    assert (tmp_path / "open-prs.json").read_text(encoding="utf-8") == "[201]\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["open-prs.detail.json", "open-prs.json"]


def test_publish_writes_the_node_retention_contract_and_the_detail(tmp_path: Path) -> None:
    runner = FakeRunner(
        {
            "o/app": ok([gh_row(201, SHA_A, "chore/meals"), gh_row(198, SHA_B)]),
            "o/skills": ok([gh_row(405), gh_row(201)]),
        }
    )
    result = publish(tmp_path, runner, ["o/app", "o/skills"])()

    numbers = json.loads((tmp_path / "open-prs.json").read_text(encoding="utf-8"))
    assert numbers == [198, 201, 405]  # 201 of both repos counts once
    assert all(isinstance(n, int) for n in numbers)
    detail = json.loads((tmp_path / "open-prs.detail.json").read_text(encoding="utf-8"))
    assert detail["schema_version"] == 1
    assert detail["repos"] == ["o/app", "o/skills"]
    assert detail["prs"][0] == {
        "repo": "o/app",
        "number": 198,
        "head_sha8": "e5cf5ce7",
        "branch": "feat/x",
        "updated_at": "2026-11-25T13:29:55Z",
    }
    assert {(p["repo"], p["number"], p["head_sha8"]) for p in detail["prs"]} >= {("o/app", 201, "3c9b6230")}
    assert result.numbers_target.endswith("open-prs.json")


def test_publish_rewrites_an_unchanged_list_so_its_mtime_stays_fresh(tmp_path: Path) -> None:
    runner = FakeRunner({"o/app": ok([gh_row(7)])})
    publish(tmp_path, runner, ["o/app"])()
    target = tmp_path / "open-prs.json"
    os.utime(target, (0, 0))
    publish(tmp_path, runner, ["o/app"])()
    assert target.stat().st_mtime > 1_000_000


@pytest.mark.parametrize(
    ("row", "field"),
    [
        ({"headRefOid": SHA_A, "headRefName": "b", "updatedAt": "2026-11-25T00:00:00Z"}, "number"),
        ({"number": 3, "headRefName": "b", "updatedAt": "2026-11-25T00:00:00Z"}, "headRefOid"),
        ({"number": 3, "headRefOid": SHA_A, "updatedAt": "2026-11-25T00:00:00Z"}, "headRefName"),
        ({"number": 3, "headRefOid": SHA_A, "headRefName": "b"}, "updatedAt"),
    ],
)
def test_a_missing_field_fails_and_keeps_the_last_good_file(tmp_path: Path, row: dict, field: str) -> None:
    seed_last_good(tmp_path)
    runner = FakeRunner({"o/app": ok([gh_row(1), row])})
    with pytest.raises(MalformedSourceError, match=field):
        publish(tmp_path, runner, ["o/app"])()
    assert_last_good_kept(tmp_path)


@pytest.mark.parametrize(
    ("stdout", "error"),
    [
        (b"not json", MalformedSourceError),
        (b'{"number": 1}', MalformedSourceError),
        (b"", MalformedSourceError),
        (json.dumps([gh_row(True)]).encode(), MalformedSourceError),  # bool is not a PR number
        (json.dumps([gh_row(-4)]).encode(), MalformedSourceError),
        (json.dumps([gh_row(4, sha="abc")]).encode(), MalformedSourceError),
        (json.dumps([gh_row(4, updated="2026-11-25T00:00:00")]).encode(), MalformedSourceError),  # naive time
        (json.dumps([gh_row(4), gh_row(4)]).encode(), MalformedSourceError),
    ],
)
def test_malformed_gh_output_fails_and_keeps_the_last_good_file(tmp_path: Path, stdout: bytes, error: type) -> None:
    seed_last_good(tmp_path)
    runner = FakeRunner({"o/app": RunResult(0, stdout, b"")})
    with pytest.raises(error):
        publish(tmp_path, runner, ["o/app"])()
    assert_last_good_kept(tmp_path)


def test_an_api_failure_in_any_repository_publishes_nothing(tmp_path: Path) -> None:
    seed_last_good(tmp_path)
    runner = FakeRunner(
        {
            "o/app": ok([gh_row(5)]),
            "o/skills": RunResult(1, b"", b"HTTP 502: Bad Gateway (https://api.github.com/graphql)"),
        }
    )
    with pytest.raises(SourceUnavailableError, match=r"o/skills exited 1: HTTP 502"):
        publish(tmp_path, runner, ["o/app", "o/skills"])()
    assert_last_good_kept(tmp_path)


def test_missing_gh_and_a_timeout_are_source_failures(tmp_path: Path) -> None:
    def missing() -> RunResult:
        raise FileNotFoundError("gh")

    def slow() -> RunResult:
        raise TimeoutError("gh did not finish within 5 s")

    seed_last_good(tmp_path)
    with pytest.raises(SourceUnavailableError, match="not found"):
        publish(tmp_path, FakeRunner({"o/app": missing}), ["o/app"])()
    with pytest.raises(SourceUnavailableError, match="did not finish"):
        publish(tmp_path, FakeRunner({"o/app": slow}), ["o/app"])()
    assert_last_good_kept(tmp_path)


def test_a_full_page_is_treated_as_truncated(tmp_path: Path) -> None:
    seed_last_good(tmp_path)
    runner = FakeRunner({"o/app": ok([gh_row(1), gh_row(2)])})
    collect = CollectSnapshot(source(runner, limit=2), FixedClock(), ["o/app"], False)
    with pytest.raises(TruncatedSourceError):
        PublishOpenPrs(collect, LocalAtomicSink(tmp_path), "open-prs.json", "open-prs.detail.json")()
    assert_last_good_kept(tmp_path)


def test_an_empty_snapshot_is_refused_unless_allowed(tmp_path: Path) -> None:
    seed_last_good(tmp_path)
    runner = FakeRunner({"o/app": ok([]), "o/skills": ok([])})
    with pytest.raises(EmptySnapshotError):
        publish(tmp_path, runner, ["o/app", "o/skills"])()
    assert_last_good_kept(tmp_path)
    publish(tmp_path, runner, ["o/app", "o/skills"], allow_empty=True)()
    assert json.loads((tmp_path / "open-prs.json").read_text(encoding="utf-8")) == []


def test_a_detail_write_failure_leaves_the_numbers_file_untouched(tmp_path: Path) -> None:
    class FailingDetail(LocalAtomicSink):
        def write(self, name: str, data: bytes) -> None:
            if name == "open-prs.detail.json":
                raise SinkError("disk full")
            super().write(name, data)

    seed_last_good(tmp_path)
    collect = CollectSnapshot(source(FakeRunner({"o/app": ok([gh_row(9)])})), FixedClock(), ["o/app"], False)
    with pytest.raises(SinkError):
        PublishOpenPrs(collect, FailingDetail(tmp_path), "open-prs.json", "open-prs.detail.json")()
    assert_last_good_kept(tmp_path)


def test_local_sink_refuses_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(SinkError, match="does not exist"):
        LocalAtomicSink(tmp_path / "absent").write("open-prs.json", b"[1]\n")


def test_ssh_sink_streams_bytes_with_their_size_and_reports_remote_failure() -> None:
    runner = FakeRunner({"ssh": RunResult(0, b"", b"")})
    from pathlib import PurePosixPath

    sink = SshAtomicSink(runner, ["ssh"], "node-a", PurePosixPath("/srv/ci"), 5.0)
    sink.write("open-prs.json", b"[1, 2]\n")
    argv, stdin = runner.calls[-1]
    assert argv[:4] == ["ssh", "-o", "BatchMode=yes", "node-a"]
    assert stdin == b"[1, 2]\n"
    assert "/srv/ci open-prs.json 7" in argv[-1]
    assert "mv -f" in argv[-1]

    runner.answers["ssh"] = RunResult(3, b"", b"size 3 != 7")
    with pytest.raises(SinkError, match="exited 3: size 3 != 7"):
        sink.write("open-prs.json", b"[1, 2]\n")


def test_settings_require_repos_and_an_absolute_remote_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("OPEN_PRS_FEED_"):
            monkeypatch.delenv(key)
    with pytest.raises(ValueError, match="repos"):
        Settings(output_dir="/x")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="owner/name"):
        Settings(repos=["just-a-name"], output_dir="/x")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="absolute POSIX"):
        Settings(repos=["o/a"], output_dir="relative", ssh_host="node-a")  # type: ignore[call-arg]
    monkeypatch.setenv("OPEN_PRS_FEED_REPOS", '["o/a","o/b"]')
    monkeypatch.setenv("OPEN_PRS_FEED_OUTPUT_DIR", "/srv/ci")
    assert Settings().repos == ["o/a", "o/b"]  # type: ignore[call-arg]


def test_cli_exits_nonzero_on_failure_and_prints_the_list_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    env = tmp_path / "feed.env"
    env.write_text(f'OPEN_PRS_FEED_REPOS=["o/app"]\nOPEN_PRS_FEED_OUTPUT_DIR={out.as_posix()}\n', encoding="utf-8")
    import open_prs_feed.composition as composition

    answers: dict = {"o/app": RunResult(1, b"", b"HTTP 401: Bad credentials")}
    monkeypatch.setattr(composition, "SubprocessRunner", lambda: FakeRunner(answers))
    runner = CliRunner()
    failed = runner.invoke(app, ["publish", "--env-file", str(env)])
    assert failed.exit_code == 1
    assert not (out / "open-prs.json").exists()

    answers["o/app"] = ok([gh_row(12)])
    done = runner.invoke(app, ["publish", "--env-file", str(env)])
    assert done.exit_code == 0, done.output
    assert json.loads((out / "open-prs.json").read_text(encoding="utf-8")) == [12]
