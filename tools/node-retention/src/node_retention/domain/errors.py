"""Typed failures of the retention policy."""

from __future__ import annotations


class RetentionError(Exception):
    """Base class: the run stops before (or instead of) deleting anything it cannot prove safe."""


class LedgerUnreadableError(RetentionError):
    """The node's job ledger could not be read or parsed, so running jobs are unknown: delete nothing."""


class UnsafeRootError(RetentionError, ValueError):
    """A configured root lies outside what the policy may ever prune (system trees, Docker data, `/`)."""
