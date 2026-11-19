"""Value types shared by the probe's layers. All sizes are bytes, all addresses are integers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Region(StrEnum):
    """Where a mapping's pages belong. Order is the classification precedence, see `domain/regions.py`."""

    JAVA_HEAP = "java_heap"
    CLASS_METADATA = "class_metadata"  # compressed class space and the CDS archive
    CODE_CACHE = "code_cache"
    THREAD_STACK = "thread_stack"
    SHMEM = "shmem"
    FILE_MAPPED = "file_mapped"  # libraries, jars, mapped data files
    BRK_HEAP = "brk_heap"  # the C allocator's `[heap]` segment
    ANON_OTHER = "anon_other"  # other anonymous native memory, including non-class metaspace without NMT


@dataclass(frozen=True, slots=True)
class AddrRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"address range end {self.end:#x} is below start {self.start:#x}")

    def contains(self, start: int, end: int) -> bool:
        return self.start <= start and end <= self.end

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Mapping:
    start: int
    end: int
    perms: str
    path: str  # "[anon]" for anonymous mappings, as psutil reports them
    rss: int
    pss: int
    swap: int

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def anonymous(self) -> bool:
        return self.path == "[anon]"


@dataclass(frozen=True, slots=True)
class RegionUsage:
    rss: int = 0
    pss: int = 0
    swap: int = 0
    mappings: int = 0

    def add(self, m: Mapping) -> RegionUsage:
        return RegionUsage(self.rss + m.rss, self.pss + m.pss, self.swap + m.swap, self.mappings + 1)


@dataclass(frozen=True, slots=True)
class ProcessBrief:
    """One `/proc/<pid>/status` row plus its cgroup: cheap enough to read for every process."""

    pid: int
    comm: str
    vm_rss: int
    vm_swap: int
    uid: int
    gid: int
    ns_pid: int  # the pid inside the innermost pid namespace (equal to pid on the host)
    start_ticks: int  # field 22 of /proc/<pid>/stat: identifies the process across pid reuse
    cgroup: str
    container_id: str | None


@dataclass(frozen=True, slots=True)
class HeapInfo:
    """Parsed `jcmd <pid> GC.heap_info`."""

    committed: int
    used: int
    reserved: AddrRange
    metaspace_used: int | None = None
    metaspace_committed: int | None = None
    class_space_used: int | None = None
    class_space_committed: int | None = None


@dataclass(frozen=True, slots=True)
class JvmLayout:
    """Address ranges used to classify a JVM's mappings, and how the heap range was found."""

    heap: AddrRange | None
    heap_source: str  # "jcmd", "xmx", "max_ram_percentage" or "none"
    class_ranges: tuple[AddrRange, ...] = ()
    code_cache: AddrRange | None = None
    heap_info: HeapInfo | None = None


@dataclass(frozen=True, slots=True)
class ClassifiedMapping:
    mapping: Mapping
    region: Region


@dataclass(slots=True)
class ProcessMemory:
    brief: ProcessBrief
    label: str
    container: str
    is_jvm: bool
    primary: bool
    regions: dict[Region, RegionUsage] = field(default_factory=dict)
    top_mappings: list[ClassifiedMapping] = field(default_factory=list)
    layout: JvmLayout | None = None
    jcmd_ok: bool | None = None  # None when jcmd was not attempted
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CgroupMemory:
    path: str  # relative to the cgroup root, e.g. "system.slice/docker-<id>.scope"
    container_id: str | None
    swap_current: int
    memory_current: int
    pgscan: int
    pgsteal: int


@dataclass(frozen=True, slots=True)
class Pressure:
    some_avg10: float
    some_avg60: float
    full_avg10: float | None  # the cpu file has no meaningful full line on older kernels
    full_avg60: float | None


@dataclass(frozen=True, slots=True)
class KernelSample:
    meminfo: dict[str, int]  # bytes
    vmstat: dict[str, int]  # raw counters
    pressure: dict[str, Pressure]  # cpu, memory, io
