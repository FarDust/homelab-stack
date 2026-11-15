"""psutil owns the process scan; paths are indexed once for every tree."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

import psutil

from node_retention.reporting.domain.models import ProcessSnapshot, path_ancestors
from node_retention.reporting.domain.ports import Budget

_ABSOLUTE = re.compile(r"/[^\s'\";|&<>]+")


class IndexedProcesses:
    def __init__(self, iterate: Callable[[], Iterable[psutil.Process]], clear_cache: Callable[[], None]) -> None:
        self.iterate = iterate
        self.clear_cache = clear_cache

    def snapshot(self, budget: Budget) -> ProcessSnapshot:
        self.clear_cache()
        paths: set[str] = set()
        observed = inaccessible = 0
        for process in self.iterate():
            budget.remaining()
            observed += 1
            try:
                with process.oneshot():
                    for path in (process.cwd(), process.exe()):
                        if path:
                            paths.update(path_ancestors(path))
                    for argument in process.cmdline():
                        budget.remaining()
                        if argument.startswith("/"):
                            paths.update(path_ancestors(argument))
                        for match in _ABSOLUTE.finditer(argument):
                            paths.update(path_ancestors(match.group()))
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue  # The snapshot records a time interval; a vanished process is not alive evidence.
            except psutil.AccessDenied:
                inaccessible += 1
        return ProcessSnapshot(frozenset(paths), observed, inaccessible)
