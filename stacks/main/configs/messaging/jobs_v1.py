"""Versioned importable demonstration jobs. RQ owns execution and retries."""

import time

from rq import get_current_job


class ControlledFailure(RuntimeError):
    """An intentionally failing first attempt for retry verification."""


def echo(value: str) -> str:
    return value


def retry_once(value: str) -> str:
    job = get_current_job()
    if job is None:
        raise ControlledFailure("Run this job through RQ")
    if not job.meta.get("first_attempt_observed"):
        job.meta["first_attempt_observed"] = True
        job.save_meta()
        raise ControlledFailure("Owned verification: fail the first execution")
    return value


def delayed_echo(value: str, seconds: int = 20) -> str:
    time.sleep(seconds)
    return value
