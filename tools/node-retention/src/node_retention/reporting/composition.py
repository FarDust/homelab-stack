"""Concrete process/filesystem/container/publisher wiring for the read-only use case."""

import os
import time

import psutil

from node_retention.reporting.adapters.docker import DockerSnapshot
from node_retention.reporting.adapters.filesystem import TreeInventory
from node_retention.reporting.adapters.ledger import TailLedger
from node_retention.reporting.adapters.processes import IndexedProcesses
from node_retention.reporting.adapters.publisher import CanonicalPublisher
from node_retention.reporting.application.report import Reporter
from node_retention.reporting.config import ReportSettings


class SystemClock:
    def wall(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


def build(settings: ReportSettings) -> Reporter:
    return Reporter(
        clock=SystemClock(),
        inventory=TreeInventory(
            settings.jobs_root, os.getuid(), lambda: frozenset(p.mountpoint for p in psutil.disk_partitions(all=True))
        ),
        processes=IndexedProcesses(psutil.process_iter, psutil.process_iter.cache_clear),
        containers=DockerSnapshot(),
        ledger=TailLedger(
            settings.ledger,
            settings.job_id,
            settings.jobs_root,
            owner=settings.owner,
            host=settings.host,
            pid=settings.pid,
        ),
        publisher=CanonicalPublisher(
            settings.publisher,
            settings.ledger,
            job_id=settings.job_id,
            owner=settings.owner,
            host=settings.host,
            pid=settings.pid,
            jobs_root=settings.jobs_root,
        ),
    )
