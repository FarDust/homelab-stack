"""Composition root: production adapters wired into the use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memory_guard.adapters.command_alert import CommandAlertSink
from memory_guard.adapters.state_file import JsonStateStore
from memory_guard.adapters.windows_probe import PsutilProcessLister, WindowsMemoryProbe
from memory_guard.application.check import CheckMemory
from memory_guard.config import Settings
from memory_guard.domain.models import GIB, Thresholds


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
    return CheckMemory(
        WindowsMemoryProbe(),
        PsutilProcessLister(),
        CommandAlertSink(settings.alert_command, settings.alert_timeout_s, settings.alert_confirm),
        JsonStateStore(settings.state_dir / "state.json"),
        SystemClock(),
        thresholds,
        settings.host,
        settings.top_n,
    )
