from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from node_retention.adapters.local import LocalFileSystem

SRC = Path(__file__).resolve().parents[1] / "src"


def test_production_modules_stay_under_the_line_ceiling() -> None:
    for path in SRC.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 1000, path


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="adapter targets Linux (st_blocks, /proc)")


@linux_only
def test_stats_use_newest_file_time_and_leave_directories_alone(tmp_path: Path) -> None:
    root = tmp_path / "unit"
    (root / "sub").mkdir(parents=True)
    old, fresh = root / "old.bin", root / "sub" / "fresh.bin"
    old.write_bytes(b"x" * 4096)
    fresh.write_bytes(b"y" * 4096)
    long_ago = time.time() - 40 * 86400
    os.utime(old, (long_ago, long_ago))
    stats = LocalFileSystem().stats(str(root))
    assert stats.size_bytes >= 8192
    assert time.time() - stats.newest_ts < 60  # the fresh file decides


@linux_only
def test_remove_deletes_trees_and_symlinks_without_following(tmp_path: Path) -> None:
    target = tmp_path / "keep"
    target.mkdir()
    (target / "f").write_text("data")
    tree = tmp_path / "tree"
    (tree / "a").mkdir(parents=True)
    (tree / "link").symlink_to(target)
    LocalFileSystem().remove(str(tree))
    assert not tree.exists() and (target / "f").read_text() == "data"


@linux_only
def test_ownership_check_tolerates_entries_that_vanish(tmp_path: Path) -> None:
    assert LocalFileSystem().owned_by_current_user(str(tmp_path / "gone")) is False


@linux_only
def test_stats_count_hardlinks_once_and_ignore_symlink_and_directory_reads(tmp_path: Path) -> None:
    root = tmp_path / "unit"
    root.mkdir()
    first = root / "a.bin"
    first.write_bytes(b"z" * 8192)
    os.link(first, root / "b.bin")
    (root / "link").symlink_to(first)
    old = time.time() - 30 * 86400
    for path in (first,):
        os.utime(path, (old, old))
    stats = LocalFileSystem().stats(str(root))
    assert 8192 <= stats.size_bytes < 16384 + 8192
    assert time.time() - stats.newest_atime > 29 * 86400  # listing and symlink reads did not refresh it
