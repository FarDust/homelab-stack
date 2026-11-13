"""Path-safety checks shared by the planner and the applier; as decided in docs/adr/node_disk_retention_adr.md."""

from __future__ import annotations

import posixpath

from node_retention.config import Settings
from node_retention.domain.errors import ProtectedImageError
from node_retention.domain.models import Outcome
from node_retention.domain.ports import Docker, FileSystem, JobLedger, Processes
from node_retention.domain.rules import contains_mount, is_within, overlaps, running_job_paths


def running_jobs(settings: Settings, jobs: JobLedger, procs: Processes) -> set[str]:
    """Paths of jobs that may still run. A ledger that cannot be read raises, so nothing is deleted.

    A job path at or above a deletion root (`/tmp`, the home directory) names a whole area rather than the job's
    scratch; it is dropped so that one broad row does not stop all retention. The idle window and the open-file
    check still protect what such a job touches.
    """
    roots = [r.as_posix() for r in settings.deletion_roots()]
    held = running_job_paths(jobs.rows(), procs.is_alive)
    return {j for j in held if not any(is_within(r, j) for r in roots)}


def unsafe_reason(
    settings: Settings,
    fs: FileSystem,
    path: str,
    job_paths: set[str],
    mount_points: set[str],
    *,
    whole_path_resolves: bool = False,
) -> tuple[Outcome, str] | None:
    """Why `path` must not be deleted, or None when it is safe as far as paths go.

    - the path lies strictly below a configured deletion root (or is a configured cache unit) and has no `..`;
    - no symlink in its ancestry leads elsewhere (`whole_path_resolves` also requires the path itself to be no
      symlink, for walks that descend into it);
    - no mount point lies at or below it, so a removal never crosses into another filesystem;
    - no job that may still run (job ledger) names a path inside it or above it.
    """
    if posixpath.normpath(path) != path or not settings.is_allowed_target(path):
        return Outcome.SKIPPED_UNSAFE, "outside the configured retention roots"
    parent = posixpath.dirname(path)
    if fs.resolve(parent) != parent:
        return Outcome.SKIPPED_UNSAFE, f"an ancestor is a symlink: {parent} resolves to {fs.resolve(parent)}"
    if whole_path_resolves and fs.resolve(path) != path:
        return Outcome.SKIPPED_UNSAFE, f"{path} is a symlink to {fs.resolve(path)}"
    if contains_mount(path, mount_points):
        return Outcome.SKIPPED_UNSAFE, "a mount point lies at or below it"
    job = next((j for j in sorted(job_paths) if overlaps(path, j)), None)
    if job is not None:
        return Outcome.SKIPPED_RUNNING_JOB, f"a running job of the ledger uses {job}"
    return None


def protected_image_violations(settings: Settings, docker: Docker) -> list[str]:
    """One line per protected image that is missing or resolves to another id; empty when all hold.

    Run before any image prune, as decided in docs/adr/node_disk_retention_adr.md. A failed lookup raises, so
    an unknown state is never read as intact.
    """
    found: list[str] = []
    for ref, expected in sorted(settings.protected_image_refs.items()):
        observed = docker.image_id(ref)
        if observed != expected:
            found.append(f"protected image {ref}: expected {expected}, observed {observed or 'missing'}")
    return found


def require_protected_images(settings: Settings, docker: Docker) -> None:
    """Raise `ProtectedImageError` naming every ref, expected id and observed id that drifted."""
    found = protected_image_violations(settings, docker)
    if found:
        raise ProtectedImageError(found)
