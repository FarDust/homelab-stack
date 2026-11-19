"""Classify a process's mappings into memory regions; parse the jcmd output that gives the JVM's address ranges.

The method and its limits are recorded in docs/adr/node_memory_probe_adr.md.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Sequence

from node_memory_probe.domain.models import (
    AddrRange,
    ClassifiedMapping,
    HeapInfo,
    JvmLayout,
    Mapping,
    Region,
    RegionUsage,
)

KIB = 1024
MIB = 1024 * KIB
_SIZE = re.compile(r"^(\d+)([kKmMgGtT]?)$")
_UNITS = {"": 1, "k": KIB, "m": MIB, "g": 1024 * MIB, "t": 1024 * 1024 * MIB}
_HEAP_LINE = re.compile(r"total (\d+)K, used (\d+)K \[(0x[0-9a-fA-F]+), (?:0x[0-9a-fA-F]+, )?(0x[0-9a-fA-F]+)\)")
_META = re.compile(r"^\s*Metaspace\s+used (\d+)K, committed (\d+)K", re.MULTILINE)
_CLASS = re.compile(r"^\s*class space\s+used (\d+)K, committed (\d+)K", re.MULTILINE)
_BOUNDS = re.compile(r"bounds \[(0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+)\]")
_CLASS_SPACE = re.compile(r"Compressed class space mapped at: (0x[0-9a-fA-F]+)-(0x[0-9a-fA-F]+)")
_CDS = re.compile(r"CDS archive\(s\) mapped at: \[(0x[0-9a-fA-F]+)-(?:0x[0-9a-fA-F]+-)?(0x[0-9a-fA-F]+)\)")
_SHMEM_PREFIXES = ("/memfd:", "/SYSV", "/dev/shm/", "/dev/zero", "[anon_shmem")
# The JVM aligns the heap reservation up to its heap alignment (region size or large page), never down.
XMX_ALIGNMENT_SLACK = 64 * MIB
PERCENT_TOLERANCE = 0.02


class JcmdParseError(ValueError):
    """jcmd answered, but not with the lines this probe reads."""


def parse_size(text: str) -> int:
    """`-Xmx` style size: digits with an optional k/m/g/t suffix."""
    match = _SIZE.match(text.strip())
    if match is None:
        raise ValueError(f"not a JVM size: {text!r}")
    return int(match.group(1)) * _UNITS[match.group(2).lower()]


def max_heap_flag(args: Sequence[str]) -> tuple[str, float] | None:
    """The heap ceiling from the command line; the last flag wins, as in HotSpot.

    Returns ("xmx", bytes) or ("max_ram_percentage", percent), or None when the JVM chose its own default.
    """
    found: tuple[str, float] | None = None
    for arg in args:
        if arg.startswith("-Xmx"):
            found = ("xmx", float(parse_size(arg[4:])))
        elif arg.startswith("-XX:MaxHeapSize="):
            found = ("xmx", float(parse_size(arg.split("=", 1)[1])))
        elif arg.startswith("-XX:MaxRAMPercentage="):
            found = ("max_ram_percentage", float(arg.split("=", 1)[1]))
    return found


def parse_heap_info(text: str) -> HeapInfo:
    """`jcmd <pid> GC.heap_info` for G1, Parallel and Serial; generations are summed and their ranges joined."""
    lines = _HEAP_LINE.findall(text)
    if not lines:
        raise JcmdParseError("GC.heap_info has no 'total NK, used NK [start, end)' line (ZGC/Shenandoah?)")
    committed = sum(int(t) for t, _, _, _ in lines) * KIB
    used = sum(int(u) for _, u, _, _ in lines) * KIB
    start = min(int(s, 16) for _, _, s, _ in lines)
    end = max(int(e, 16) for _, _, _, e in lines)
    meta = _META.search(text)
    klass = _CLASS.search(text)
    return HeapInfo(
        committed=committed,
        used=used,
        reserved=AddrRange(start, end),
        metaspace_used=int(meta.group(1)) * KIB if meta else None,
        metaspace_committed=int(meta.group(2)) * KIB if meta else None,
        class_space_used=int(klass.group(1)) * KIB if klass else None,
        class_space_committed=int(klass.group(2)) * KIB if klass else None,
    )


def parse_code_cache(text: str) -> AddrRange:
    """`jcmd <pid> Compiler.codecache`: the union of every code heap's bounds."""
    bounds = _BOUNDS.findall(text)
    if not bounds:
        raise JcmdParseError("Compiler.codecache has no 'bounds [low, high, end]' line")
    return AddrRange(min(int(lo, 16) for lo, _, _ in bounds), max(int(hi, 16) for _, _, hi in bounds))


def parse_class_ranges(text: str) -> tuple[AddrRange, ...]:
    """`jcmd <pid> VM.info`: the compressed class space and the CDS archive, when the JVM maps them."""
    ranges = [AddrRange(int(a, 16), int(b, 16)) for a, b in _CLASS_SPACE.findall(text)]
    ranges += [AddrRange(int(a, 16), int(b, 16)) for a, b in _CDS.findall(text)]
    return tuple(ranges)


def find_heap_by_size(mappings: Sequence[Mapping], low: int, high: int) -> AddrRange | None:
    """First run of contiguous anonymous mappings whose span is within [low, high] bytes.

    The heap is one reservation of the maximum heap size that the JVM later splits into committed and
    uncommitted parts, so its mappings are adjacent and anonymous; the run starts at a mapping boundary.
    """
    ordered = sorted(mappings, key=lambda m: m.start)
    for i, first in enumerate(ordered):
        if not first.anonymous:
            continue
        end = first.end
        j = i
        while True:
            span = end - first.start
            if low <= span <= high:
                return AddrRange(first.start, end)
            if span > high or j + 1 >= len(ordered):
                break
            nxt = ordered[j + 1]
            if nxt.start != end or not nxt.anonymous:
                break
            end, j = nxt.end, j + 1
    return None


def heap_from_flags(
    mappings: Sequence[Mapping], args: Sequence[str], memory_limit: int | None
) -> tuple[AddrRange | None, str]:
    """Heap range from `-Xmx`/`MaxRAMPercentage` when jcmd is not available for this JVM."""
    flag = max_heap_flag(args)
    if flag is None:
        return None, "none"
    kind, value = flag
    if kind == "xmx":
        size = int(value)
        heap = find_heap_by_size(mappings, size, size + XMX_ALIGNMENT_SLACK)
        return heap, "xmx" if heap else "none"
    if memory_limit is None:
        return None, "none"
    target = memory_limit * value / 100
    found = find_heap_by_size(mappings, int(target * (1 - PERCENT_TOLERANCE)), int(target * (1 + PERCENT_TOLERANCE)))
    return found, "max_ram_percentage" if found else "none"


def _in_any(ranges: Iterable[AddrRange], m: Mapping) -> bool:
    return any(r.start <= m.start < r.end for r in ranges)


def classify(m: Mapping, layout: JvmLayout | None, stack_pointers: Sequence[int]) -> Region:
    """Precedence: JVM ranges, thread stacks, shared memory, file-backed, brk heap, other anonymous."""
    if layout is not None:
        if layout.heap is not None and layout.heap.start <= m.start < layout.heap.end:
            return Region.JAVA_HEAP
        if _in_any(layout.class_ranges, m):
            return Region.CLASS_METADATA
        if layout.code_cache is not None and layout.code_cache.start <= m.start < layout.code_cache.end:
            return Region.CODE_CACHE
    if m.path.startswith("[stack"):
        return Region.THREAD_STACK
    k = bisect.bisect_left(stack_pointers, m.start)
    if k < len(stack_pointers) and stack_pointers[k] < m.end:
        return Region.THREAD_STACK
    if m.path.startswith(_SHMEM_PREFIXES):
        return Region.SHMEM
    if m.path == "[heap]":
        return Region.BRK_HEAP
    if m.path.startswith("["):  # [anon], [anon:<name>], [vdso], [vvar]
        return Region.ANON_OTHER
    return Region.FILE_MAPPED


def summarize(
    mappings: Sequence[Mapping], layout: JvmLayout | None, stack_pointers: Iterable[int], top: int
) -> tuple[dict[Region, RegionUsage], list[ClassifiedMapping]]:
    """Per-region totals (every region present, zero when empty) and the `top` mappings by swap."""
    sps = sorted(stack_pointers)
    totals = {region: RegionUsage() for region in Region}
    classified: list[ClassifiedMapping] = []
    for m in mappings:
        region = classify(m, layout, sps)
        totals[region] = totals[region].add(m)
        if m.swap > 0:
            classified.append(ClassifiedMapping(m, region))
    classified.sort(key=lambda c: (-c.mapping.swap, c.mapping.start))
    return totals, classified[:top]
