"""Apply a plan: write the manifest first, then delete with a last-moment safety re-check."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from node_retention.application.metrics import CHECK_FILE, RUN_FILE, render_metrics, render_run_metrics
from node_retention.application.planning import Ports
from node_retention.application.safety import protected_image_violations, running_jobs, unsafe_reason
from node_retention.config import Settings
from node_retention.domain.errors import ImageLookupError
from node_retention.domain.models import (
    Candidate,
    Manifest,
    ManifestEntry,
    Outcome,
    Plan,
)
from node_retention.domain.ports import Ledger, Publisher
from node_retention.domain.rules import in_use


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Applier:
    def __init__(self, settings: Settings, ports: Ports, ledger: Ledger, publisher: Publisher) -> None:
        self._s = settings
        self._p = ports
        self._ledger = ledger
        self._pub = publisher

    def manifest_path(self, run_id: str) -> Path:
        return self._s.state_dir / f"manifest-{run_id}.json"

    def apply(self, plan: Plan, run_id: str, pid: int) -> Manifest:
        s, p = self._s, self._p
        manifest = Manifest(
            host=s.host,
            run_id=run_id,
            started_at=p.clock.now(),
            root_free_before=p.fs.free_bytes(s.root_mount.as_posix()),
            entries=[ManifestEntry(candidate=c) for c in plan.candidates],
        )
        s.state_dir.mkdir(parents=True, exist_ok=True)
        # The manifest exists on disk, with path, size, age and reason, before anything is deleted.
        self._write(manifest, run_id)
        self._ledger.append(self._row("start", run_id, pid, manifest))
        try:
            # Checked again here: the planner's answer may be minutes old. The start row exists first, so a lookup
            # error (fail closed) still leaves a start and a failed end row in the ledger.
            manifest.protected_image_violations = protected_image_violations(s, p.docker)
            for entry in manifest.entries:
                self._run_entry(entry)
        except ImageLookupError:
            # Fail closed: the image state is unknown, so the run ends as failed and the error reaches the caller.
            manifest.finished_at = p.clock.now()
            self._write(manifest, run_id)
            self._ledger.append(self._row("end", run_id, pid, manifest, failed=True))
            raise
        manifest.finished_at = p.clock.now()
        manifest.root_free_after = p.fs.free_bytes(s.root_mount.as_posix())
        self._write(manifest, run_id)
        failed = bool(manifest.protected_image_violations) or any(e.outcome is Outcome.FAILED for e in manifest.entries)
        self._ledger.append(self._row("end", run_id, pid, manifest, failed=failed))
        self._pub.publish(CHECK_FILE, render_metrics(s, free_bytes=manifest.root_free_after, now=manifest.finished_at))
        self._pub.publish(
            RUN_FILE,
            render_run_metrics(
                s,
                now=manifest.finished_at,
                freed_bytes=manifest.freed_bytes,
                success=not failed,
                planned_bytes=plan.total_bytes,
            ),
        )
        return manifest

    def _write(self, manifest: Manifest, run_id: str) -> None:
        path = self.manifest_path(run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def _run_entry(self, entry: ManifestEntry) -> None:
        c = entry.candidate
        try:
            if c.action == "docker_image_prune":
                if self._image_guard_failed(entry):
                    return
                entry.freed_bytes = self._p.docker.prune_dangling_images()
                entry.outcome = Outcome.DELETED
            elif c.action == "prune_stale_files":
                if self._unsafe(entry, c, whole_path_resolves=True):
                    return
                cutoff = self._p.clock.now() - c.min_idle_seconds
                entry.freed_bytes = self._p.fs.prune_stale_files(c.path, cutoff, self._p.procs.open_paths())
                entry.outcome = Outcome.DELETED
            elif c.action == "docker_builder_prune":
                entry.freed_bytes = self._p.docker.prune_build_cache(self._s.docker_build_cache_days * 24)
                entry.outcome = Outcome.DELETED
            else:
                self._remove_path(entry, c)
        except ImageLookupError:
            raise
        except Exception as exc:
            entry.outcome = Outcome.FAILED
            entry.detail = f"{type(exc).__name__}: {exc}"

    def _image_guard_failed(self, entry: ManifestEntry) -> bool:
        """Fail the image prune when a protected image drifted since the manifest was written."""
        found = protected_image_violations(self._s, self._p.docker)
        if not found:
            return False
        entry.outcome, entry.detail = Outcome.FAILED, "image prune refused: " + "; ".join(found)
        return True

    def _remove_path(self, entry: ManifestEntry, c: Candidate) -> None:
        p = self._p
        if not p.fs.exists(c.path):
            entry.outcome = Outcome.SKIPPED_MISSING
            return
        if self._unsafe(entry, c):
            return
        st = p.fs.stats(c.path)
        if p.clock.now() - st.newest_ts < c.min_idle_seconds:
            entry.outcome, entry.detail = Outcome.SKIPPED_RECENT, "used since the plan was made"
            return
        if st.has_socket:
            entry.outcome, entry.detail = Outcome.SKIPPED_OPEN, "holds a Unix socket"
            return
        if in_use(c.path, p.procs.open_paths()):
            entry.outcome = Outcome.SKIPPED_OPEN
            return
        if in_use(c.path, p.docker.mount_sources()):
            entry.outcome = Outcome.SKIPPED_MOUNTED
            return
        try:
            p.fs.remove(c.path)
        except PermissionError:
            # Job containers leave root-owned files behind; a one-shot helper container removes them.
            p.docker.remove_path_as_root(c.path)
            entry.detail = "removed through the root helper container"
        if p.fs.exists(c.path):
            entry.outcome, entry.detail = Outcome.FAILED, "path still exists after removal"
            return
        entry.outcome, entry.freed_bytes = Outcome.DELETED, st.size_bytes

    def _unsafe(self, entry: ManifestEntry, c: Candidate, *, whole_path_resolves: bool = False) -> bool:
        """Re-check path safety just before deleting, re-reading the job ledger (an unreadable one raises)."""
        p = self._p
        jobs = running_jobs(self._s, p.jobs, p.procs)
        found = unsafe_reason(self._s, p.fs, c.path, jobs, p.fs.mount_points(), whole_path_resolves=whole_path_resolves)
        if found is None:
            return False
        entry.outcome, entry.detail = found
        return True

    def _row(self, event: str, run_id: str, pid: int, manifest: Manifest, failed: bool = False) -> dict[str, object]:
        row: dict[str, object] = {
            "ts": iso(self._p.clock.now()),
            "event": event,
            "id": run_id,
            "who": "retention",
            "class": "io-light",
            "what": "retention-apply",
            "host": self._s.host,
            "pid": pid,
        }
        if event == "end":
            row |= {
                "result": "exit=1" if failed else "exit=0",
                "freed_bytes": manifest.freed_bytes,
                "root_free_before": manifest.root_free_before,
                "root_free_after": manifest.root_free_after,
                "manifest": str(self.manifest_path(run_id)),
            }
        return row
