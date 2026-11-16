"""Bounded tail of the existing ledger, never a new state store or writer."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from node_retention.reporting.domain.models import LedgerSnapshot, ReportError
from node_retention.reporting.domain.ports import Budget

_OWNER = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_BRACKET = re.compile(r"\[([^]\r\n]+)\]")


class TailLedger:
    def __init__(
        self,
        path: Path,
        job_id: str,
        jobs_root: Path,
        *,
        owner: str,
        host: str,
        pid: int,
        maximum_bytes: int = 16_384_000,
        maximum_rows: int = 4000,
    ) -> None:
        self.path = path
        self.job_id = job_id
        self.jobs_root = jobs_root
        self.owner, self.host, self.pid = owner, host, pid
        self.maximum_bytes = maximum_bytes
        self.maximum_rows = maximum_rows

    def snapshot(self, budget: Budget) -> LedgerSnapshot:
        budget.remaining()
        try:
            with self.path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                offset = max(0, size - self.maximum_bytes)
                handle.seek(offset)
                data = handle.read(self.maximum_bytes)
        except OSError as error:
            raise ReportError("existing job ledger is unreadable") from error
        if offset:
            data = data.partition(b"\n")[2]
        owners: set[str] = set()
        trees: set[str] = set()
        containers: set[str] = set()
        deadline = None
        malformed = 0
        lifecycle: dict[str, tuple[str, str]] = {}
        for line in data.splitlines()[-self.maximum_rows :]:
            budget.remaining()
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                if re.search(rb'"id"\s*:\s*"' + re.escape(self.job_id.encode()) + rb'"', line):
                    raise ReportError("own job has malformed ledger evidence; original deadline is unknown") from error
                malformed += 1
                continue
            if not isinstance(row, dict):
                malformed += 1
                continue
            event, identity, where = row.get("event"), row.get("id"), row.get("where")
            if event in ("start", "end", "refused") and isinstance(identity, str) and isinstance(where, str):
                path = PurePosixPath(where)
                if (
                    path.is_absolute()
                    and ".." not in path.parts
                    and path.is_relative_to(self.jobs_root.as_posix())
                    and str(path) != self.jobs_root.as_posix()
                ):
                    lifecycle[identity] = (event, str(path))
            if row.get("id") == self.job_id and row.get("event") == "start":
                try:
                    for field, expected_value in (("who", self.owner), ("host", self.host), ("pid", self.pid)):
                        if row[field] != expected_value or (field == "pid" and type(row[field]) is not int):
                            raise ReportError(f"own start {field} does not match caller")
                    if not isinstance(row["where"], str) or not PurePosixPath(row["where"]).is_absolute():
                        raise ReportError("own start where has invalid resource scope")
                    expected = row["expected_s"]
                    started = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                    if type(expected) is not int or expected <= 0 or started.utcoffset() is None:
                        raise ValueError("invalid original deadline evidence")
                    deadline = started.timestamp() + expected
                except (KeyError, TypeError, ValueError, AttributeError) as error:
                    raise ReportError("own start row lacks valid persisted original deadline") from error
            owner = row.get("who")
            if isinstance(owner, str) and _OWNER.fullmatch(owner):
                owners.add(owner)
            kind = row.get("kind")
            if kind not in ("stale-tree-report", "stale-container-report"):
                continue
            target = trees if kind == "stale-tree-report" else containers
            names = row.get("reported_names")
            if "reported_names" in row:
                if isinstance(names, list) and all(isinstance(name, str) for name in names):
                    target.update(names)
                else:
                    malformed += 1
            else:
                what = row.get("what")
                if isinstance(what, str):
                    target.update(_BRACKET.findall(what))
        if deadline is None:
            raise ReportError("own persisted start row absent from bounded ledger window")
        active = frozenset(path for event, path in lifecycle.values() if event == "start")
        terminal = tuple((path, identity) for identity, (event, path) in lifecycle.items() if event == "end")
        return LedgerSnapshot(
            frozenset(owners), frozenset(trees), frozenset(containers), deadline, malformed, active, terminal
        )
