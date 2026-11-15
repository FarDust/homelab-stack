"""Reuse the configured ledger publisher; never write the shared ledger here."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from node_retention.reporting.domain.models import Finding, ReportError
from node_retention.reporting.domain.ports import Budget


class CanonicalPublisher:
    def __init__(
        self, executable: Path, ledger: Path, *, job_id: str, owner: str, host: str, pid: int, jobs_root: Path
    ) -> None:
        self.executable, self.ledger = executable, ledger
        self.job_id, self.owner, self.host = job_id, owner, host
        self.pid, self.jobs_root = pid, jobs_root

    def publish(self, findings: tuple[Finding, ...], budget: Budget) -> None:
        if not findings or len(findings) > 2:
            raise ReportError("report publication requires one bounded nonempty chunk")
        kind, owner = findings[0].kind, findings[0].owner
        if any(f.kind != kind or f.owner != owner for f in findings):
            raise ReportError("report publication mixes owner or resource kind")
        names = [f.name for f in findings]
        what = f"old resource metadata of {owner} (owner review only; retention NOT authorized): " + "; ".join(
            f"[{f.name}] idle {f.age_hours:.1f} h; lifecycle={f.lifecycle}" for f in findings
        )
        extra = json.dumps(
            {
                "kind": kind,
                "owner": owner,
                "reported_names": names,
                "review": "owner retention decision required",
                "resource_evidence": [
                    {
                        "name": f.name,
                        "device": f.device,
                        "inode": f.inode,
                        "allocated_bytes": f.allocated_bytes,
                        "root_owned": f.root_owned,
                        "lifecycle": f.lifecycle,
                        "terminal_job_ids": f.related_terminal_job_ids[:4],
                        "terminal_job_count": len(f.related_terminal_job_ids),
                        "retention_authorized": False,
                    }
                    for f in findings
                ],
            },
            ensure_ascii=False,
        )[1:-1]
        command = [
            str(self.executable),
            "append",
            "--ledger",
            str(self.ledger),
            "--event",
            "note",
            "--class",
            "light",
            "--what=" + what,
            "--where",
            str(self.jobs_root),
            "--id",
            self.job_id,
            "--who",
            self.owner,
            "--host",
            self.host,
            "--pid",
            str(self.pid),
            "--extra-members",
            extra,
        ]
        try:
            remaining = budget.remaining()
            subprocess.run(
                ["/usr/bin/timeout", "--signal=KILL", str(remaining), *command],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ReportError("canonical report publication failed; receipt is not complete") from error
