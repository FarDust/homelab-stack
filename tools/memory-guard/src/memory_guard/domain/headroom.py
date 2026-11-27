"""Commit-headroom textfile for the node-exporter textfile collector (docs/adr/memory_guard_adr.md, addendum 0.4.0)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from memory_guard.domain.errors import ProbeError

TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
TEXTFILE_NAME = "memory_guard_commit.prom"
TEXTFILE_PATH = f"{TEXTFILE_DIR}/{TEXTFILE_NAME}"
HEADROOM_METRIC = "memory_guard_commit_headroom_bytes"
TIMESTAMP_METRIC = "memory_guard_commit_sample_timestamp_seconds"
# Prometheus label values may hold anything, but a plain token needs no escaping and keeps the contract exact.
HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


@dataclass(frozen=True)
class HeadroomReading:
    """Free virtual memory (commit limit minus commit charge) and when it was sampled."""

    headroom_bytes: int
    sampled_at_unix: float

    def __post_init__(self) -> None:
        if isinstance(self.headroom_bytes, bool) or not isinstance(self.headroom_bytes, int):
            raise ProbeError(f"commit headroom must be an integer byte count, got {type(self.headroom_bytes).__name__}")
        if self.headroom_bytes < 0:
            raise ProbeError(
                f"commit headroom is negative ({self.headroom_bytes} bytes): commit charge above the commit limit "
                "means the probe read is inconsistent; check GetPerformanceInfo"
            )
        if not math.isfinite(self.sampled_at_unix) or self.sampled_at_unix <= 0:
            raise ProbeError(f"sample timestamp must be a positive finite unix time, got {self.sampled_at_unix!r}")


def render_textfile(reading: HeadroomReading, host_label: str) -> str:
    if not HOST_LABEL_PATTERN.fullmatch(host_label):
        raise ValueError(f"host label {host_label!r} must match {HOST_LABEL_PATTERN.pattern}")
    label = f'{{host="{host_label}"}}'
    return (
        f"# HELP {HEADROOM_METRIC} Windows free virtual memory (commit limit minus commit charge) in bytes.\n"
        f"# TYPE {HEADROOM_METRIC} gauge\n"
        f"{HEADROOM_METRIC}{label} {reading.headroom_bytes}\n"
        f"# HELP {TIMESTAMP_METRIC} Unix time when memory-guard sampled the commit headroom.\n"
        f"# TYPE {TIMESTAMP_METRIC} gauge\n"
        f"{TIMESTAMP_METRIC}{label} {reading.sampled_at_unix:.3f}\n"
    )


class PublishStatus(StrEnum):
    DISABLED = "disabled"
    DISTRO_NOT_RUNNING = "distro_not_running"
    PUBLISHED = "published"


@dataclass(frozen=True)
class PublishOutcome:
    status: PublishStatus
    reading: HeadroomReading | None = None
