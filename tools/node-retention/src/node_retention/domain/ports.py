"""Ports the application layer depends on; adapters implement them."""

from __future__ import annotations

from typing import Protocol

from node_retention.domain.models import StaleFiles, TreeStats


class FileSystem(Protocol):
    def children(self, path: str) -> list[str]: ...
    def stats(self, path: str) -> TreeStats: ...
    def exists(self, path: str) -> bool: ...
    def stale_files(self, path: str, cutoff_ts: float) -> StaleFiles: ...
    def prune_stale_files(self, path: str, cutoff_ts: float, open_paths: set[str]) -> int: ...
    def remove(self, path: str) -> None: ...
    def owned_by_current_user(self, path: str) -> bool: ...
    def free_bytes(self, path: str) -> int: ...

    def resolve(self, path: str) -> str:
        """Canonical path with every symlink resolved (`os.path.realpath`)."""
        ...

    def mount_points(self) -> set[str]:
        """Every mount point of this mount namespace (`/proc/self/mountinfo`)."""
        ...

    def device(self, path: str) -> int:
        """Device id (`st_dev` of `lstat`) of the filesystem that holds `path`; raises when it does not exist."""
        ...

    def read_record(self, path: str) -> str | None:
        """Text of a small record file (at most 4 KiB) read without updating its atime, or None when absent.

        Reading must not refresh the atime: a tree's newest read is part of its idle time.
        """
        ...


class Processes(Protocol):
    def open_paths(self) -> set[str]:
        """Paths held by processes visible to this user: file descriptors, cwd, executable and mapped files."""
        ...

    def is_alive(self, pid: int) -> bool: ...


class Docker(Protocol):
    def mount_sources(self) -> set[str]:
        """Host paths bind-mounted into any container (running or stopped)."""
        ...

    def image_id(self, ref: str) -> str | None:
        """Full image id (`sha256:...`) the tag or reference resolves to, or None when no such image exists."""
        ...

    def data_root(self) -> str:
        """Docker's data directory (`DockerRootDir`): images and build cache live on its filesystem."""
        ...

    def prune_dangling_images(self) -> int: ...
    def remove_path_as_root(self, path: str) -> None: ...
    def prune_build_cache(self, older_than_hours: int) -> int: ...
    def build_cache_reclaimable(self) -> int: ...
    def dangling_images_reclaimable(self) -> int: ...


class Ledger(Protocol):
    def append(self, row: dict[str, object]) -> None: ...


class JobLedger(Protocol):
    skipped_lines: list[int]  # malformed rows the last read skipped (old rows only; recent ones raise)

    def rows(self) -> list[dict[str, object]]:
        """Every row of the node's job ledger.

        Raises `LedgerUnreadableError` when the ledger is missing, unreadable or holds a malformed row, so the
        caller deletes nothing (fail closed).
        """
        ...


class OpenPullRequests(Protocol):
    def numbers(self) -> set[int] | None:
        """PR numbers that are open in the repositories CI runs for, or None when that is unknown.

        Unknown is a valid answer: the node may have no GitHub credentials. Callers then protect every path
        tied to any PR number (fail closed).
        """
        ...


class Publisher(Protocol):
    def publish(self, name: str, text: str) -> None: ...


class Clock(Protocol):
    def now(self) -> float: ...
