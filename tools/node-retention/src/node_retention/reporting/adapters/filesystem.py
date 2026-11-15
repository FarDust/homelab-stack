"""Read-only inventory; symlink/mount/permission uncertainty is explicit."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Iterable
from pathlib import Path

from node_retention.reporting.domain.models import ReportError, Tree, TreeEvidence
from node_retention.reporting.domain.ports import Budget

_OWNER = re.compile(r"^who=([A-Za-z0-9._-]{1,128})(?: |$)")


class TreeInventory:
    def __init__(self, root: Path, current_uid: int, mount_reader: Callable[[], frozenset[str]]) -> None:
        self.root = root
        self.current_uid = current_uid
        self.mount_reader = mount_reader
        self.mounts: frozenset[str] | None = None

    def trees(self, budget: Budget) -> Iterable[Tree]:
        budget.remaining()
        try:
            self.mounts = self.mount_reader()
            if not self.mounts:
                raise ReportError("mount table is empty; tree evidence is unknown")
            budget.remaining()
            if self.root.resolve(strict=True) != self.root or self.root.is_symlink():
                raise ReportError("report jobs root is not a canonical real directory")
            with os.scandir(self.root) as entries:
                for entry in entries:
                    budget.remaining()
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    identity = entry.stat(follow_symlinks=False)
                    marker = Path(entry.path) / ".agent-job"
                    owner = None
                    try:
                        if marker.is_symlink():
                            raise ReportError("job marker is a symlink; owner evidence is unknown")
                        with marker.open(encoding="utf-8") as handle:
                            first = handle.readline(4097)
                        match = _OWNER.match(first)
                        if not match or len(first) > 4096:
                            raise ReportError("job marker has invalid owner evidence")
                        owner = match.group(1)
                    except FileNotFoundError:
                        pass  # Marker absence deliberately selects the historical longest-prefix policy.
                    yield Tree(entry.path, entry.name, owner, identity.st_dev, identity.st_ino)
        except OSError as error:
            raise ReportError("tree inventory cannot be verified") from error

    def evidence(self, tree: Tree, budget: Budget) -> TreeEvidence:
        if self.mounts is None:
            raise ReportError("tree evidence requires the bounded inventory mount snapshot")
        path = Path(tree.path)
        try:
            root_stat = path.lstat()
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or path.parent != self.root
                or (root_stat.st_dev, root_stat.st_ino) != (tree.device, tree.inode)
            ):
                raise ReportError("tree identity changed during report")
            size = 0
            newest = 0.0
            root_owned = False
            seen: set[tuple[int, int]] = set()
            pending = [(path, 0)]
            while pending:
                budget.remaining()
                current, depth = pending.pop()
                info = current.lstat()
                if info.st_dev != root_stat.st_dev or (current != path and str(current) in self.mounts):
                    raise ReportError("tree crosses a filesystem boundary; retained as unknown")
                root_owned = root_owned or info.st_uid != self.current_uid
                if depth <= 2:
                    newest = max(newest, info.st_mtime)
                identity = (info.st_dev, info.st_ino)
                if identity not in seen:
                    size += info.st_blocks * 512
                    seen.add(identity)
                if stat.S_ISDIR(info.st_mode):
                    with os.scandir(current) as entries:
                        for entry in entries:
                            budget.remaining()
                            pending.append((Path(entry.path), depth + 1))
            return TreeEvidence(size, newest, root_owned, root_stat.st_dev, root_stat.st_ino)
        except OSError as error:
            raise ReportError("tree changed or is unreadable; retained as unknown") from error
