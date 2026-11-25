"""Typed failures. Any of them ends the run before the consumer file is replaced."""

from __future__ import annotations


class FeedError(Exception):
    """Base class: the snapshot is not complete and verified, so nothing new is published."""


class SourceUnavailableError(FeedError):
    """The pull request source could not be queried (missing binary, timeout, nonzero exit)."""


class MalformedSourceError(FeedError):
    """The source answered, but the answer does not match the expected schema."""


class TruncatedSourceError(FeedError):
    """The source returned as many rows as the limit, so the list may be partial."""


class EmptySnapshotError(FeedError):
    """Every repository answered with no open pull request and an empty snapshot was not allowed."""


class SinkError(FeedError):
    """Writing or verifying a published file failed; the previous file is left in place."""
