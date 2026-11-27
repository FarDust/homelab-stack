"""Composition root: production adapters wired into the use case."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from memory_guard.adapters.command_alert import CommandAlertSink
from memory_guard.adapters.gpu_pdh import PdhGpuMemoryProbe
from memory_guard.adapters.ollama import OllamaPsProbe
from memory_guard.adapters.reclaim_log import JsonlReclaimLog
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.adapters.windows_probe import PsutilProcessLister, PsutilVmmemProbe, WindowsMemoryProbe
from memory_guard.adapters.wsl import WslCli, WslTextfileWriter
from memory_guard.application.attribution import AttributeCause
from memory_guard.application.check import CheckMemory
from memory_guard.application.publish_headroom import PublishHeadroom
from memory_guard.application.reclaim import ReclaimWslCache
from memory_guard.config import Settings
from memory_guard.domain.headroom import TEXTFILE_PATH
from memory_guard.domain.models import GIB, ReclaimPolicy, Thresholds


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build_check(settings: Settings) -> CheckMemory:
    thresholds = Thresholds(
        int(settings.min_free_virtual_gb * GIB),
        int(settings.min_free_ram_gb * GIB),
        settings.samples,
        timedelta(minutes=settings.alert_interval_min),
    )
    probe = WindowsMemoryProbe()
    clock = SystemClock()
    policy = ReclaimPolicy(
        settings.reclaim_enabled,
        settings.reclaim_samples,
        timedelta(minutes=settings.reclaim_min_interval_min),
        settings.reclaim_max_per_hour,
        settings.reclaim_settle_s,
    )
    reclaimer = ReclaimWslCache(
        WslCli(settings.wsl_distro, settings.reclaim_timeout_s),
        PsutilVmmemProbe(),
        probe,
        JsonlReclaimLog(settings.state_dir / "reclaim.jsonl"),
        clock,
        policy,
        time.sleep,
    )
    return CheckMemory(
        probe,
        PsutilProcessLister(),
        CommandAlertSink(settings.alert_command, settings.alert_timeout_s, settings.alert_confirm),
        JsonStateStore(settings.state_dir / "state.json"),
        clock,
        thresholds,
        settings.host,
        settings.top_n,
        reclaimer,
        AttributeCause(
            PdhGpuMemoryProbe(),
            OllamaPsProbe(settings.ollama_url, settings.ollama_timeout_s),
            clock,
            int(settings.gpu_other_gb * GIB),
        ),
    )


def build_publish_headroom(settings: Settings) -> PublishHeadroom:
    return PublishHeadroom(
        settings.headroom_publish_enabled,
        WindowsMemoryProbe(),
        WslCli(settings.wsl_distro, settings.headroom_timeout_s),
        WslTextfileWriter(settings.wsl_distro, TEXTFILE_PATH, settings.headroom_timeout_s),
        SystemClock(),
        settings.headroom_host_label,
    )
