"""Actual native filesystem boundary; Linux-specific observations stay explicit."""

import os
import time

import pytest

from node_retention.reporting.adapters.filesystem import TreeInventory
from node_retention.reporting.domain.models import ReportError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux retention filesystem semantics")


class Budget:
    def remaining(self):
        return 5


def test_symlinks_are_not_traversed_marker_owner_and_allocated_size_are_real(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    (tree / ".agent-job").write_text("who=lane id=test\n123 456\n")
    (tree / "file").write_bytes(b"x" * 8192)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("retained")
    (tree / "link").symlink_to(outside, target_is_directory=True)
    (jobs / "external").symlink_to(outside, target_is_directory=True)
    adapter = TreeInventory(jobs, os.getuid(), lambda: frozenset({"/"}))
    trees = list(adapter.trees(Budget()))
    assert len(trees) == 1
    assert trees[0].marker_owner == "lane"
    assert adapter.evidence(trees[0], Budget()).allocated_bytes >= 8192
    assert (outside / "sentinel").read_text() == "retained"


def test_bind_mount_same_device_and_unacquired_mount_evidence_are_unknown(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    child = tree / "mount"
    child.mkdir()
    adapter = TreeInventory(jobs, os.getuid(), lambda: frozenset({"/", str(child)}))
    entries = list(adapter.trees(Budget()))
    with pytest.raises(ReportError, match="filesystem boundary"):
        adapter.evidence(entries[0], Budget())


def test_top_two_level_idle_characterization_preserves_existing_policy(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    (tree / "work").mkdir()
    deep = tree / "work" / "deep"
    deep.mkdir()
    (deep / "fresh").write_text("fresh")
    old = time.time() - 25_000
    for path in (deep, tree / "work", tree):
        os.utime(path, (old, old))
    adapter = TreeInventory(jobs, os.getuid(), lambda: frozenset({"/"}))
    entries = list(adapter.trees(Budget()))
    assert adapter.evidence(entries[0], Budget()).newest_mtime == old


def test_replaced_tree_cannot_borrow_old_marker_ownership(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    adapter = TreeInventory(jobs, os.getuid(), lambda: frozenset({"/"}))
    observed = next(iter(adapter.trees(Budget())))
    tree.rename(jobs / "preserved-original")
    tree.mkdir()
    with pytest.raises(ReportError, match="identity changed"):
        adapter.evidence(observed, Budget())


def test_foreign_non_root_owner_retains_historical_permission_warning(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    # Use a different observer UID rather than mutating ownership or requiring root.
    adapter = TreeInventory(jobs, os.getuid() + 1, lambda: frozenset({"/"}))
    observed = next(iter(adapter.trees(Budget())))
    assert adapter.evidence(observed, Budget()).root_owned is True


def test_tree_replaced_after_initial_identity_read_is_not_returned_with_old_inode(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tree = jobs / "lane-old"
    tree.mkdir()
    (tree / "original").write_text("preserved")
    adapter = TreeInventory(jobs, os.getuid(), lambda: frozenset({"/"}))
    observed = next(iter(adapter.trees(Budget())))

    class ReplacingBudget(Budget):
        changed = False

        def remaining(self):
            if not self.changed:
                self.changed = True
                tree.rename(jobs / "preserved-original")
                tree.mkdir()
                (tree / "replacement").write_text("different observation")
            return super().remaining()

    with pytest.raises(ReportError, match="identity changed during measurement"):
        adapter.evidence(observed, ReplacingBudget())
    assert (jobs / "preserved-original" / "original").read_text() == "preserved"
