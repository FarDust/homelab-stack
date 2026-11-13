"""A protected image is never pruned, and a prune never runs with -a/--all; as decided in docs/adr/node_disk_retention_adr.md."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from node_retention import cli
from node_retention.adapters.docker_cli import DockerCli
from node_retention.application.applying import Applier
from node_retention.application.planning import Planner, Ports
from node_retention.application.safety import require_protected_images
from node_retention.config import Settings
from node_retention.domain.errors import ImageLookupError, ProtectedImageError
from node_retention.domain.models import Outcome
from tests.fakes import (
    GIB,
    FakeClock,
    FakeDocker,
    FakeFs,
    FakeJobs,
    FakeLedger,
    FakeProcs,
    FakePublisher,
    make_settings,
)

REF = "example/cleanup:1.0-abc"
GOOD = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def _ports(docker: FakeDocker, root_free: int = 100 * GIB) -> Ports:
    return Ports(
        fs=FakeFs(root_free=root_free), procs=FakeProcs(), docker=docker, clock=FakeClock(), jobs=FakeJobs(FakeLedger())
    )


def _run(tmp_path: Path, images: dict[str, str]):
    docker = FakeDocker(dangling=GIB)
    docker.images = images
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD})
    ports = _ports(docker)
    plan = Planner(settings, ports).build()
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "run", 1)
    return docker, plan, manifest


def test_image_prune_runs_when_protected_ref_is_intact(tmp_path: Path) -> None:
    docker, plan, manifest = _run(tmp_path, {REF: GOOD})
    assert plan.protected_image_violations == []
    assert docker.calls == ["image"]
    assert manifest.protected_image_violations == []


@pytest.mark.parametrize("images", [{}, {REF: OTHER}], ids=["missing", "drifted"])
def test_image_prune_refuses_when_protected_ref_missing_or_drifted(tmp_path: Path, images: dict[str, str]) -> None:
    docker, plan, manifest = _run(tmp_path, images)
    observed = images.get(REF, "missing")
    assert "image" not in docker.calls
    (line,) = plan.protected_image_violations
    assert REF in line and GOOD in line and observed in line
    assert manifest.protected_image_violations == plan.protected_image_violations
    assert not any(c.action == "docker_image_prune" for c in plan.candidates)


def test_prune_refused_when_guard_fails_between_plan_and_apply(tmp_path: Path) -> None:
    docker = FakeDocker(dangling=GIB)
    docker.images = {REF: GOOD}
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD})
    ports = _ports(docker)
    plan = Planner(settings, ports).build()
    docker.images = {}  # the image is removed after the plan was made
    manifest = Applier(settings, ports, FakeLedger(), FakePublisher()).apply(plan, "run", 1)
    entry = next(e for e in manifest.entries if e.candidate.action == "docker_image_prune")
    assert entry.outcome is Outcome.FAILED and REF in entry.detail
    assert docker.calls == []


def test_require_protected_images_raises_with_ref_expected_and_observed() -> None:
    docker = FakeDocker()
    docker.images = {REF: OTHER}
    settings = make_settings(Path("/x"), protected_image_refs={REF: GOOD})
    with pytest.raises(ProtectedImageError) as err:
        require_protected_images(settings, docker)
    assert REF in str(err.value) and GOOD in str(err.value) and OTHER in str(err.value)


def test_no_protected_refs_by_default(tmp_path: Path) -> None:
    assert make_settings(tmp_path).protected_image_refs == {}


def test_settings_load_the_mapping_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODE_RETENTION_PROTECTED_IMAGE_REFS", json.dumps({REF: GOOD}))
    monkeypatch.setenv("NODE_RETENTION_HOST", "n")
    monkeypatch.setenv("NODE_RETENTION_HOME", "/h")
    monkeypatch.setenv("NODE_RETENTION_CI_ROOT", "/h/ci")
    monkeypatch.setenv("NODE_RETENTION_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("NODE_RETENTION_LEDGER_PATH", str(tmp_path / "l"))
    assert Settings().protected_image_refs == {REF: GOOD}  # type: ignore[call-arg]


def test_verify_images_command_exits_nonzero_on_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docker = FakeDocker()
    docker.images = {REF: OTHER}
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD})
    ports = _ports(docker, root_free=GIB)
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda _s: ports)
    result = CliRunner().invoke(cli.app, ["verify-images"])
    assert result.exit_code == 1
    flat = result.output.replace("\n", "")
    assert REF in flat and GOOD in flat and OTHER in flat
    docker.images = {REF: GOOD}
    assert CliRunner().invoke(cli.app, ["verify-images"]).exit_code == 0


def test_apply_exits_nonzero_when_guard_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docker = FakeDocker(dangling=GIB)
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD}, textfile_dir=tmp_path / "tf")
    ports = _ports(docker)
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda _s: ports)
    monkeypatch.setattr(cli, "TextfilePublisher", lambda *_a, **_k: FakePublisher())
    monkeypatch.setattr(cli, "JsonlLedger", lambda _p: FakeLedger())
    result = CliRunner().invoke(cli.app, ["apply"])
    assert result.exit_code == 1
    assert docker.calls == []


def _recorder(argvs: list[list[str]]):
    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        argvs.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Total reclaimed space: 0B\n", stderr="")

    return run


def test_no_prune_command_ever_contains_all_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    argvs: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recorder(argvs))
    docker = DockerCli("busybox:1.37")
    docker.prune_dangling_images()
    docker.prune_build_cache(168)
    assert len(argvs) == 2 and all("prune" in a for a in argvs)
    for argv in argvs:
        assert not {"-a", "--all", "--volumes"} & set(argv)
    for forbidden in ("-a", "--all", "--all=true", "--volumes"):
        with pytest.raises(ValueError):
            docker._run("image", "prune", "--force", forbidden)
    assert len(argvs) == 2  # the refused commands never reached subprocess


def test_image_id_distinguishes_missing_from_lookup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        if argv[-1] == "gone":
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Error: No such image: gone")
        if argv[-1] == "broken":
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Cannot connect to the Docker daemon")
        return subprocess.CompletedProcess(argv, 0, stdout=GOOD + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    docker = DockerCli("busybox:1.37")
    assert docker.image_id("ok") == GOOD
    assert docker.image_id("gone") is None
    with pytest.raises(ImageLookupError):
        docker.image_id("broken")


def test_image_id_rejects_an_empty_or_malformed_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    for out in ("", "   ", "abc", "sha256:short"):
        monkeypatch.setattr(
            subprocess, "run", lambda argv, _o=out, **_k: subprocess.CompletedProcess(argv, 0, stdout=_o, stderr="")
        )
        with pytest.raises(ImageLookupError):
            DockerCli("busybox:1.37").image_id("x")


@pytest.mark.parametrize("bad", ["", "sha256:", "sha256:" + "A" * 64, "sha256:" + "a" * 63, "a" * 64])
def test_expected_id_must_be_a_full_sha256(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        make_settings(tmp_path, protected_image_refs={REF: bad})


FORBIDDEN = ["-a", "-a=true", "--all", "--all=true", "-af", "-fa", "-aF", "--volumes", "--volumes=true"]
PRUNES = [
    ["image", "prune"],
    ["builder", "prune"],
    ["system", "prune"],
    ["container", "prune"],
    ["volume", "prune"],
    ["network", "prune"],
]


@pytest.mark.parametrize("flag", FORBIDDEN)
@pytest.mark.parametrize("prune", PRUNES, ids=lambda p: p[0])
def test_every_prune_subcommand_refuses_all_spellings(
    monkeypatch: pytest.MonkeyPatch, prune: list[str], flag: str
) -> None:
    argvs: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recorder(argvs))
    for args in ([*prune, "--force", flag], [*prune, flag, "--force"], [*prune, "--force", "-a", flag]):
        with pytest.raises(ValueError):
            DockerCli("busybox:1.37")._run(*args)
    assert argvs == []


def test_allowed_prune_arguments_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    argvs: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recorder(argvs))
    docker = DockerCli("busybox:1.37")
    docker._run("image", "prune", "--force")
    docker._run("builder", "prune", "--force", "--filter", "until=168h")
    docker._run("image", "prune", "-f", "--filter", "until=24h")
    assert len(argvs) == 3


class _BrokenDocker(FakeDocker):
    """Answers the first `fail_on` lookups, then fails like a daemon error."""

    def __init__(self, ok_lookups: int, **kw: int) -> None:
        super().__init__(**kw)
        self.ok_lookups = ok_lookups
        self.lookups = 0

    def image_id(self, ref: str) -> str | None:
        self.lookups += 1
        if self.lookups > self.ok_lookups:
            raise ImageLookupError("daemon error (test)")
        return GOOD


@pytest.mark.parametrize(("ok", "stage"), [(1, "per-entry recheck"), (0, "start of apply")])
def test_lookup_error_during_apply_aborts_the_run(tmp_path: Path, ok: int, stage: str) -> None:
    """ok=1: planner answers, the apply-start check fails; ok=2 below: only the per-entry recheck fails."""
    docker = _BrokenDocker(ok_lookups=ok + 1 if stage == "per-entry recheck" else 1, dangling=GIB)
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD})
    ports = _ports(docker)
    plan = Planner(settings, ports).build()
    ledger = FakeLedger()
    with pytest.raises(ImageLookupError):
        Applier(settings, ports, ledger, FakePublisher()).apply(plan, "run", 1)
    assert docker.calls == []
    if stage == "per-entry recheck":
        assert [r["event"] for r in ledger.rows] == ["start", "end"] and ledger.rows[-1]["result"] == "exit=1"


def test_lookup_error_in_plan_aborts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD})
    with pytest.raises(ImageLookupError):
        Planner(settings, _ports(_BrokenDocker(ok_lookups=0, dangling=GIB))).build()


def test_guard_with_violation_exits_nonzero_and_prunes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docker = FakeDocker(dangling=GIB)
    docker.images = {REF: OTHER}
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD}, textfile_dir=tmp_path / "tf")
    ports = _ports(docker, root_free=GIB)  # under the 8 GiB floor, so guard runs apply
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda _s: ports)
    monkeypatch.setattr(cli, "TextfilePublisher", lambda *_a, **_k: FakePublisher())
    monkeypatch.setattr(cli, "JsonlLedger", lambda _p: FakeLedger())
    result = CliRunner().invoke(cli.app, ["guard"])
    assert result.exit_code == 1
    assert docker.calls == []


def test_cli_apply_reports_failure_metric_on_lookup_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pub = FakePublisher()
    settings = make_settings(tmp_path, protected_image_refs={REF: GOOD}, textfile_dir=tmp_path / "tf")
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "_ports", lambda _s: _ports(_BrokenDocker(ok_lookups=0)))
    monkeypatch.setattr(cli, "TextfilePublisher", lambda *_a, **_k: pub)
    monkeypatch.setattr(cli, "JsonlLedger", lambda _p: FakeLedger())
    result = CliRunner().invoke(cli.app, ["apply"])
    assert result.exit_code != 0 and isinstance(result.exception, ImageLookupError)
    assert "node_retention_run.prom" in pub.files
