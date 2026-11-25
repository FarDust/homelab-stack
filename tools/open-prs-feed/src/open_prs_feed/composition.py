"""Composition root: production adapters wired into the use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from open_prs_feed.adapters.gh_cli import GhCliSource
from open_prs_feed.adapters.process import CommandRunner, SubprocessRunner
from open_prs_feed.adapters.sinks import LocalAtomicSink, SshAtomicSink
from open_prs_feed.application.publish import CollectSnapshot, PublishOpenPrs
from open_prs_feed.config import Settings
from open_prs_feed.domain.ports import AtomicSink


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build_collect(settings: Settings, runner: CommandRunner | None = None) -> CollectSnapshot:
    runner = runner or SubprocessRunner()
    source = GhCliSource(runner, settings.gh_command, settings.limit, settings.gh_timeout_s)
    return CollectSnapshot(source, SystemClock(), settings.repos, settings.allow_empty)


def build_sink(settings: Settings, runner: CommandRunner | None = None) -> AtomicSink:
    if settings.ssh_host is None:
        return LocalAtomicSink(settings.local_dir())
    return SshAtomicSink(
        runner or SubprocessRunner(),
        settings.ssh_command,
        settings.ssh_host,
        settings.remote_dir(),
        settings.ssh_timeout_s,
    )


def build_publish(settings: Settings, runner: CommandRunner | None = None) -> PublishOpenPrs:
    runner = runner or SubprocessRunner()
    return PublishOpenPrs(
        build_collect(settings, runner), build_sink(settings, runner), settings.numbers_file, settings.detail_file
    )
