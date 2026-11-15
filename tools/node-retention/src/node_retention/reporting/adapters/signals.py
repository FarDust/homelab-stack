"""Scoped cancellation handling; restoration preserves the caller's handlers."""

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from node_retention.reporting.domain.models import ReportCancelled


@contextmanager
def cancellation_signals() -> Iterator[None]:
    def cancel(number: int, frame: FrameType | None) -> None:
        raise ReportCancelled(number)

    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        for number in previous:
            signal.signal(number, cancel)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def cleanup_signals() -> Iterator[None]:
    # A first TERM during cleanup is propagated after the owned worker is stopped.
    with creation_signals():
        yield


@contextmanager
def creation_signals() -> Iterator[None]:
    """Defer cancellation until the newly created worker has an owned handle."""
    pending: list[int] = []

    def defer(number: int, frame: FrameType | None) -> None:
        pending.append(number)

    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        for number in previous:
            signal.signal(number, defer)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    if pending:
        raise ReportCancelled(pending[0])
