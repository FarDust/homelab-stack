"""Ports the use case depends on; adapters live in `open_prs_feed.adapters`."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from open_prs_feed.domain.models import OpenPr


class PullRequestSource(Protocol):
    def open_prs(self, repo: str) -> list[OpenPr]:
        """Every open PR of `repo`, or a FeedError. Never a partial list."""
        ...


class AtomicSink(Protocol):
    def describe(self, name: str) -> str: ...

    def write(self, name: str, data: bytes) -> None:
        """Replace file `name` with `data` in one rename, after checking the written size; or raise SinkError."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...
