"""Hard bound blocking observations using the standard library's owned process group."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from node_retention.reporting.adapters.signals import cleanup_signals, creation_signals
from node_retention.reporting.config import ReportSettings
from node_retention.reporting.domain.models import Outcome, ReportCancelled, ReportStatus


def unknown(reason: str, started: float) -> Outcome:
    return Outcome(
        status=ReportStatus.UNKNOWN,
        findings=(),
        reasons=(reason,),
        trees_examined=0,
        processes_examined=0,
        published_notes=0,
        elapsed_seconds=time.monotonic() - started,
    )


def stop_owned_worker(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """Verify the owned worker group; native command watchdogs retain their own deadlines."""
    try:
        with cleanup_signals():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The owned group has already exited; the return code still needs verification.
            except PermissionError:
                return False
            try:
                process.communicate(timeout=max(0.001, timeout))
            except subprocess.TimeoutExpired:
                return False  # Uninterruptible I/O is unknown, never claimed to be cleaned up.
            return process.poll() is not None
    except ReportCancelled as error:
        error.worker_pid = process.pid
        error.worker_termination_verified = process.poll() is not None
        raise


def supervise(settings: ReportSettings) -> Outcome:
    started = time.monotonic()
    remaining = min(settings.maximum_seconds, settings.deadline_epoch - time.time())
    if remaining <= 0.15:
        return unknown("original job deadline has no remaining report/cleanup budget", started)
    finish = started + remaining
    environment = os.environ.copy()
    environment["NODE_RETENTION_REPORT_CONTROLLER_PID"] = str(os.getpid())
    environment["NODE_RETENTION_REPORT_PHASE_DEADLINE_EPOCH"] = str(
        min(settings.deadline_epoch, time.time() + remaining - 0.1)
    )
    process = None
    try:
        with creation_signals():
            process = subprocess.Popen(
                [
                    str(settings.parent_death_guard),
                    "--pdeathsig",
                    "KILL",
                    "--",
                    sys.executable,
                    "-B",
                    "-m",
                    "node_retention.reporting.worker_entry",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
        stdout, _ = process.communicate(timeout=max(0.001, finish - time.monotonic() - 0.1))
    except subprocess.TimeoutExpired:
        stopped = stop_owned_worker(process, finish - time.monotonic())
        return unknown("whole-report hard deadline exhausted; unvisited evidence is unknown", started).model_copy(
            update={"worker_termination_verified": stopped, "worker_pid": process.pid}
        )
    except ReportCancelled as error:
        if process is not None:
            error.worker_pid = process.pid
            error.worker_termination_verified = stop_owned_worker(process, min(0.1, finish - time.monotonic()))
        raise
    except OSError as error:
        stopped = None if process is None else stop_owned_worker(process, min(0.1, finish - time.monotonic()))
        return unknown(f"owned report worker launch or I/O failed ({type(error).__name__})", started).model_copy(
            update={"worker_termination_verified": stopped, "worker_pid": None if process is None else process.pid}
        )
    except BaseException:
        if process is not None:
            stop_owned_worker(process, min(0.1, finish - time.monotonic()))
        raise
    try:
        outcome = Outcome.model_validate_json(stdout)
    except ValueError:
        return unknown(f"report worker exit={process.returncode}; missing or malformed typed outcome", started)
    expected_exit = 0 if outcome.status == ReportStatus.COMPLETE else 2
    if process.returncode != expected_exit:
        return unknown("report worker failed; outcome is not a successful receipt", started)
    return outcome.model_copy(update={"worker_termination_verified": True, "worker_pid": process.pid})
