"""Native Linux lifecycle evidence in a synthetic namespace; no cleanup API is invoked."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux native lifecycle tools")


def owned_process_exited(pid: int, birth: float) -> bool:
    try:
        process = psutil.Process(pid)
        return process.create_time() != birth or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return path


def namespace(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for number in range(100):
        tree = jobs / f"lane-g{number:07x}"
        tree.mkdir()
        (tree / ".agent-job").write_text("who=lane id=synthetic\n1 1\n")
        (tree / "sentinel").write_text("retained synthetic data")
        for path in (tree / ".agent-job", tree / "sentinel", tree):
            os.utime(path, (time.time() - 25_000, time.time() - 25_000))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable(binaries / "docker", "import sys\nif sys.argv[1] not in ('ps','inspect'): raise SystemExit(99)\n")
    executable(
        binaries / "readlink",
        "import os,sys,time\n"
        "if sys.argv[-1].endswith('/cwd'):\n"
        " time.sleep(.02)\n"
        " with open(os.environ['TEST_COUNTER'],'a') as out:out.write('.')\n"
        "os.execv('/usr/bin/readlink',['/usr/bin/readlink',*sys.argv[1:]])\n",
    )
    publisher = executable(
        binaries / "publisher",
        "import json,os,sys\nfrom pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "if Path(args[args.index('--ledger')+1]) != Path(os.environ['TEST_LEDGER']):raise SystemExit(99)\n"
        "with open(os.environ['TEST_NOTES'],'a') as out:out.write(json.dumps({'appended':True})+'\\n')\n",
    )
    pid = os.getpid()
    job_id = f"20261115T010000Z-{pid}"
    started = int(time.time())
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "id": job_id,
                "event": "start",
                "ts": datetime.now(UTC).isoformat(),
                "expected_s": 30,
                "who": "caller",
                "host": os.uname().nodename,
                "pid": pid,
                "where": str(jobs / "caller"),
            }
        )
        + "\n"
    )
    environment = os.environ.copy()
    environment.update(
        PATH=str(binaries) + os.pathsep + environment["PATH"],
        TMPDIR=str(tmp_path),
        TMP=str(tmp_path),
        TEMP=str(tmp_path),
        LANES_HOME=str(tmp_path),
        LANES_LEDGER=str(ledger),
        LANES_JOBS_ROOT=str(jobs),
        LANES_GC_REPORT_AGE_H="6",
        LANES_SWAP_DEV="none",
        LANES_ID=job_id,
        LANES_RUN=str(pid),
        LANES_WHO="caller",
        LANES_REPORT_START_EPOCH=str(started),
        LANES_REPORT_EXPECTED_S="30",
        LANES_LEDGER_BIN=str(publisher),
        TEST_COUNTER=str(tmp_path / "readlink-count"),
        TEST_LEDGER=str(ledger),
        TEST_NOTES=str(tmp_path / "synthetic-notes"),
        NODE_RETENTION_REPORT_MAXIMUM_SECONDS="3",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment, jobs, publisher


def test_native_read_only_before_after_is_bounded_and_does_not_delete(tmp_path, record_property):
    for program in ("/usr/bin/timeout", "/usr/bin/setpriv", "/usr/bin/bash"):
        assert Path(program).is_file(), f"required existing native tool is absent: {program}"
    environment, jobs, _ = namespace(tmp_path)
    fixture = Path(__file__).parent / "fixtures/legacy_gate.sh"
    legacy = tmp_path / "legacy-run.sh"
    legacy.write_text('set -u\n. "$TEST_LEGACY"\nlanes_ledger() { return 0; }\n_lanes_gc_report\n')
    environment["TEST_LEGACY"] = str(fixture)
    started = time.monotonic()
    process = subprocess.Popen(
        ["/usr/bin/bash", str(legacy)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        process.communicate(timeout=1)
        legacy_timeout = False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=1)
        legacy_timeout = True
    legacy_elapsed = time.monotonic() - started
    assert legacy_timeout, "the injected per-process delay did not reproduce the historical unbounded path"
    count_path = Path(environment["TEST_COUNTER"])
    old_calls = len(count_path.read_text())
    assert old_calls >= 2
    package = Path(__file__).parents[2]
    shim = package.parents[1] / "host-config/ci-job-reporting/gc-report.sh"
    console = Path(sys.executable).with_name("node-retention-report")
    assert console.is_file(), "the installed console contract is missing"
    modern = tmp_path / "modern-run.sh"
    modern.write_text('set -u\n. "$TEST_SHIM"\nlanes_report_stale_once\n')
    environment.update(TEST_SHIM=str(shim), LANES_REPORT_EXECUTABLE=str(console))
    started = time.monotonic()
    result = subprocess.run(["/usr/bin/bash", str(modern)], env=environment, capture_output=True, text=True, timeout=6)
    modern_elapsed = time.monotonic() - started
    outcomes = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert outcomes, "native reporter did not provide an explicit outcome"
    outcome = outcomes[-1]
    assert outcome["status"] in ("complete", "partial", "unknown")
    if outcome["status"] == "complete":
        assert result.returncode == 0
        assert outcome["trees_examined"] == 100
    else:
        assert result.returncode != 0
        assert outcome["reasons"]
        assert any("incomplete" in reason or "deadline" in reason for reason in outcome["reasons"])
    assert modern_elapsed < 5.8
    assert len(count_path.read_text()) == old_calls, "modern reporting invoked a per-process shell readlink"
    assert len(list(jobs.glob("*/sentinel"))) == 100
    assert all(p.read_text() == "retained synthetic data" for p in jobs.glob("*/sentinel"))
    record_property("legacy_timeout_seconds", legacy_elapsed)
    record_property("legacy_readlink_processes", old_calls)
    record_property("modern_lifecycle_seconds", modern_elapsed)
    record_property("modern_status", outcome["status"])


def test_worker_parent_handshake_denies_before_application_import(tmp_path):
    environment = os.environ.copy()
    environment["NODE_RETENTION_REPORT_CONTROLLER_PID"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-m", "node_retention.reporting.worker_entry"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.returncode == 2
    assert "original parent is absent" in result.stderr


def test_kernel_parent_death_guard_terminates_only_its_owned_child(tmp_path):
    marker = tmp_path / "owned-child"
    controller = tmp_path / "controller.py"
    ready = tmp_path / "child-ready"
    controller.write_text(
        "import subprocess,sys,time,json,psutil,os\nfrom pathlib import Path\n"
        "child=subprocess.Popen(['/usr/bin/setpriv','--pdeathsig','KILL','--',sys.executable,'-c',"
        "'from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text(\"ready\");time.sleep(30)',sys.argv[2]])\n"
        "target=Path(sys.argv[1]);temporary=target.with_suffix('.new')\n"
        "temporary.write_text(json.dumps({'pid':child.pid,'birth':psutil.Process(child.pid).create_time()}))\n"
        "os.replace(temporary,target)\ntime.sleep(30)\n"
    )
    process = subprocess.Popen([sys.executable, "-B", str(controller), str(marker), str(ready)])
    child_identity = None
    try:
        finish = time.monotonic() + 2
        while not (marker.exists() and ready.exists()) and time.monotonic() < finish:
            time.sleep(0.01)
        assert marker.exists() and ready.exists()
        child_identity = json.loads(marker.read_text())
        child_pid = child_identity["pid"]
        process.kill()
        process.wait(timeout=1)
        finish = time.monotonic() + 2
        while time.monotonic() < finish:
            if owned_process_exited(child_pid, child_identity["birth"]):
                break
            time.sleep(0.01)
        else:
            pytest.fail("owned worker remained running after its original parent died")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        if child_identity is not None:
            try:
                child = psutil.Process(child_identity["pid"])
                if child.create_time() == child_identity["birth"] and child.status() != psutil.STATUS_ZOMBIE:
                    child.kill()
                    child.wait(timeout=1)
            except psutil.NoSuchProcess:
                pass


def test_native_command_watchdog_survives_worker_death_and_bounds_grandchild(tmp_path):
    marker = tmp_path / "descendants.json"
    child_code = (
        "import subprocess,sys,time,json,os;from pathlib import Path;"
        "grandchild=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "target=Path(sys.argv[1]);temporary=target.with_suffix('.new');"
        "temporary.write_text(json.dumps([os.getpid(),grandchild.pid]));"
        "os.replace(temporary,target);time.sleep(30)"
    )
    worker_code = "import subprocess,sys,time;subprocess.Popen(sys.argv[1:]);time.sleep(30)"
    started = time.monotonic()
    worker = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-c",
            worker_code,
            "/usr/bin/timeout",
            "--signal=KILL",
            "1",
            sys.executable,
            "-B",
            "-c",
            child_code,
            str(marker),
        ]
    )
    identities = []
    try:
        finish = started + 0.8
        while not marker.exists() and time.monotonic() < finish:
            time.sleep(0.01)
        assert marker.exists(), "native command did not reach controlled descendant phase"
        identities = [(pid, psutil.Process(pid).create_time()) for pid in json.loads(marker.read_text())]
        worker.kill()
        worker.wait(timeout=1)
        finish = started + 2
        while time.monotonic() < finish:
            if all(owned_process_exited(pid, birth) for pid, birth in identities):
                break
            time.sleep(0.01)
        else:
            pytest.fail("native command watchdog left a descendant running after its original deadline")
        assert time.monotonic() - started < 2
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=1)
        for pid, birth in identities:
            try:
                process = psutil.Process(pid)
                if process.create_time() == birth and process.status() != psutil.STATUS_ZOMBIE:
                    process.kill()
                    process.wait(timeout=1)
            except psutil.NoSuchProcess:
                pass


def test_production_adapter_watchdog_timeout_kills_child_and_grandchild(tmp_path):
    from node_retention.reporting.adapters.docker import DockerSnapshot
    from node_retention.reporting.domain.models import ReportError

    marker = tmp_path / "production-descendants.json"
    binary = executable(
        tmp_path / "docker-probe",
        "import subprocess,sys,time,json,os\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
        f"target=Path({str(marker)!r});temporary=target.with_suffix('.new')\n"
        "temporary.write_text(json.dumps([os.getpid(),child.pid]));os.replace(temporary,target)\n"
        "time.sleep(30)\n",
    )

    class Budget:
        def remaining(self):
            return 0.6

    started = time.monotonic()
    with pytest.raises(ReportError, match="exceeded report budget"):
        DockerSnapshot(str(binary))._call(["ps", "-q"], Budget())
    assert time.monotonic() - started < 2
    assert marker.exists(), "production adapter did not reach descendant phase"
    for pid in json.loads(marker.read_text()):
        try:
            assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
