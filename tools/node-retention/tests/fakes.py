"""In-memory implementations of the ports, used instead of mocks."""

from __future__ import annotations

from pathlib import Path

from node_retention.config import GIB, Settings
from node_retention.domain.errors import LedgerUnreadableError
from node_retention.domain.models import StaleFiles, TreeStats

NOW = 2_000_000_000.0
DAY = 86400.0
HOUR = 3600.0


class FakeFs:
    """Paths map to (size, newest_ts, owned_by_me). A directory's children are paths one level below it."""

    def __init__(self, root_free: int) -> None:
        self.nodes: dict[str, tuple[int, float, float, bool]] = {}
        self.root_free = root_free
        self.removed: list[str] = []
        self.stale: dict[str, int] = {}
        self.pruned_stale: list[str] = []
        self.refuse_removal: set[str] = set()
        self.symlinks: dict[str, str] = {}  # path prefix -> where it really points
        self.mounts: set[str] = set()
        self.sockets: set[str] = set()  # trees that contain a Unix socket
        self.on_stats = lambda path: None  # hook: runs before each stats() call

    def add(self, path: str, size: int, age_s: float, owned: bool = True, read_age_s: float | None = None) -> None:
        """`age_s` is the age of the newest write; `read_age_s` the age of the newest read (default: same)."""
        self.nodes[path] = (size, NOW - age_s, NOW - (age_s if read_age_s is None else read_age_s), owned)

    def children(self, path: str) -> list[str]:
        prefix = path.rstrip("/") + "/"
        return sorted(p for p in self.nodes if p.startswith(prefix) and "/" not in p[len(prefix) :])

    def stats(self, path: str) -> TreeStats:
        self.on_stats(path)
        size, mtime, atime, _ = self.nodes[path]
        return TreeStats(size_bytes=size, newest_mtime=mtime, newest_atime=atime, has_socket=path in self.sockets)

    def resolve(self, path: str) -> str:
        for link, target in self.symlinks.items():
            if path == link or path.startswith(link + "/"):
                return target + path[len(link) :]
        return path

    def mount_points(self) -> set[str]:
        return set(self.mounts)

    def exists(self, path: str) -> bool:
        return path in self.nodes

    def stale_files(self, path: str, cutoff_ts: float) -> StaleFiles:
        size = self.stale.get(path, 0)
        return StaleFiles(size_bytes=size, count=1 if size else 0)

    def prune_stale_files(self, path: str, cutoff_ts: float, open_paths: set[str]) -> int:
        size = self.stale.pop(path, 0)
        self.root_free += size
        self.pruned_stale.append(path)
        return size

    def owned_by_current_user(self, path: str) -> bool:
        return self.nodes[path][3]

    def free_bytes(self, path: str) -> int:
        return self.root_free

    def remove(self, path: str) -> None:
        if path in self.refuse_removal:
            raise PermissionError(path)
        size = self.nodes.pop(path)[0]
        self.root_free += size
        self.removed.append(path)


class FakeProcs:
    def __init__(self, open_paths: set[str] | None = None, alive: set[int] | None = None) -> None:
        self.open = open_paths or set()
        self.alive = alive or set()

    def open_paths(self) -> set[str]:
        return set(self.open)

    def is_alive(self, pid: int) -> bool:
        return pid in self.alive


class FakeDocker:
    def __init__(self, mounts: set[str] | None = None, dangling: int = 0, cache: int = 0) -> None:
        self.mounts = mounts or set()
        self.dangling = dangling
        self.cache = cache
        self.calls: list[str] = []
        self.on_root_remove = lambda path: None

    def mount_sources(self) -> set[str]:
        return set(self.mounts)

    def dangling_images_reclaimable(self) -> int:
        return self.dangling

    def build_cache_reclaimable(self) -> int:
        return self.cache

    def remove_path_as_root(self, path: str) -> None:
        self.calls.append(f"root-rm:{path}")
        self.on_root_remove(path)

    def prune_dangling_images(self) -> int:
        self.calls.append("image")
        return self.dangling

    def prune_build_cache(self, older_than_hours: int) -> int:
        self.calls.append(f"builder:{older_than_hours}")
        return self.cache


class FakeLedger:
    """Records appended rows; `job_rows` is what the job-ledger reader returns."""

    def __init__(self, job_rows: list[dict[str, object]] | None = None) -> None:
        self.rows: list[dict[str, object]] = []
        self.job_rows: list[dict[str, object]] = job_rows or []
        self.unreadable = False

    def append(self, row: dict[str, object]) -> None:
        self.rows.append(row)

    def read_rows(self) -> list[dict[str, object]]:
        if self.unreadable:
            raise LedgerUnreadableError("ledger unreadable (test)")
        return list(self.job_rows)


class FakeJobs:
    """JobLedger port backed by a FakeLedger."""

    def __init__(self, ledger: FakeLedger) -> None:
        self.ledger = ledger

    def rows(self) -> list[dict[str, object]]:
        return self.ledger.read_rows()


class FakePublisher:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def publish(self, name: str, text: str) -> None:
        self.files[name] = text


class FakeClock:
    def now(self) -> float:
        return NOW


def make_settings(tmp: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "host": "node-a",
        "home": Path("/h"),
        "ci_root": Path("/h/ci"),
        "state_dir": tmp / "state",
        "ledger_path": tmp / "ledger.jsonl",
        "cache_roots": [Path("/h/.cache")],
        "cache_units": [Path("/h/ci/uv-cache")],
        "root_free_floor_gib": 8.0,
        "cache_budget_gib": 6.0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


__all__ = [
    "DAY",
    "GIB",
    "HOUR",
    "NOW",
    "FakeClock",
    "FakeDocker",
    "FakeFs",
    "FakeJobs",
    "FakeLedger",
    "FakeProcs",
    "FakePublisher",
    "make_settings",
]
