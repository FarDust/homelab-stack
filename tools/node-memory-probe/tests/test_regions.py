from __future__ import annotations

import pytest

from node_memory_probe.domain.models import AddrRange, JvmLayout, Mapping, Region
from node_memory_probe.domain.regions import (
    JcmdParseError,
    find_heap_by_size,
    heap_from_flags,
    max_heap_flag,
    parse_class_ranges,
    parse_code_cache,
    parse_heap_info,
    parse_size,
    summarize,
)

GIB = 1024**3
MIB = 1024**2

# Shapes copied from a JDK 21 G1 JVM (addresses kept, sizes as printed).
HEAP_INFO = """55:
 garbage-first heap   total 6291456K, used 2244600K [0x0000000540000000, 0x0000000800000000)
  region size 8192K, 51 young (417792K), 1 survivors (8192K)
 Metaspace       used 530362K, committed 536320K, reserved 1507328K
  class space    used 106639K, committed 109376K, reserved 1048576K
"""
CODECACHE = """55:
CodeHeap 'non-profiled nmethods': size=128224Kb used=69598Kb max_used=72081Kb free=58626Kb
 bounds [0x000075214bac8000, 0x0000752150148000, 0x0000752153800000]
CodeHeap 'profiled nmethods': size=128220Kb used=54138Kb max_used=82054Kb free=74081Kb
 bounds [0x0000752143800000, 0x0000752148850000, 0x000075214b537000]
CodeHeap 'non-nmethods': size=5700Kb used=3774Kb max_used=3859Kb free=1925Kb
 bounds [0x000075214b537000, 0x000075214b917000, 0x000075214bac8000]
"""
VM_INFO = """Heap address: 0x0000000540000000, size: 11264 MB, Compressed Oops mode: Zero based, Oop shift amount: 3
CDS archive(s) mapped at: [0x00007520c7000000-0x00007520c7c9e000-0x00007520c7c9e000), size 13230080, SharedBaseAddress: 0x00007520c7000000, ArchiveRelocationMode: 1.
Compressed class space mapped at: 0x00007520c8000000-0x0000752108000000, reserved size: 1073741824
"""
PARALLEL = """ PSYoungGen      total 76288K, used 3932K [0x00000000eab00000, 0x00000000f0000000, 0x0000000100000000)
 ParOldGen       total 175104K, used 0K [0x00000000c0000000, 0x00000000cab00000, 0x00000000eab00000)
"""


def anon(start: int, size: int, swap: int = 0, rss: int = 0, perms: str = "rw-p") -> Mapping:
    return Mapping(start, start + size, perms, "[anon]", rss, rss, swap)


def test_sizes_and_last_heap_flag_wins() -> None:
    assert parse_size("11G") == 11 * GIB
    assert parse_size("524288k") == 512 * MIB
    assert parse_size("1048576") == 1048576
    with pytest.raises(ValueError):
        parse_size("lots")
    assert max_heap_flag(["-Xms1g", "-Xmx1g", "-Xms512m", "-Xmx512m"]) == ("xmx", 512 * MIB)
    assert max_heap_flag(["-XX:MaxRAMPercentage=70"]) == ("max_ram_percentage", 70.0)
    assert max_heap_flag(["-jar", "server.jar"]) is None


def test_heap_info_g1_and_parallel() -> None:
    g1 = parse_heap_info(HEAP_INFO)
    assert g1.reserved == AddrRange(0x540000000, 0x800000000)
    assert g1.reserved.size == 11 * GIB
    assert g1.committed == 6 * GIB and g1.used == 2244600 * 1024
    assert g1.metaspace_used == 530362 * 1024 and g1.class_space_committed == 109376 * 1024
    par = parse_heap_info(PARALLEL)
    assert par.reserved == AddrRange(0xC0000000, 0x100000000)
    assert par.committed == (76288 + 175104) * 1024
    with pytest.raises(JcmdParseError):
        parse_heap_info(" ZHeap           used 50M, capacity 1024M, max capacity 4096M\n")


def test_code_cache_and_class_ranges() -> None:
    assert parse_code_cache(CODECACHE) == AddrRange(0x752143800000, 0x752153800000)
    with pytest.raises(JcmdParseError):
        parse_code_cache("55:\nCodeCache: size=1Kb\n")
    assert parse_class_ranges(VM_INFO) == (
        AddrRange(0x7520C8000000, 0x752108000000),
        AddrRange(0x7520C7000000, 0x7520C7C9E000),
    )


def test_heap_found_by_xmx_among_contiguous_anonymous_mappings() -> None:
    base = 0x540000000
    maps = [
        anon(0x10000000, 64 * MIB),
        anon(base, 6 * GIB),  # committed part
        anon(base + 6 * GIB, 5 * GIB, perms="---p"),  # reserved, uncommitted
        anon(base + 11 * GIB, 1 * GIB),  # class space directly after the heap
    ]
    assert find_heap_by_size(maps, 11 * GIB, 11 * GIB) == AddrRange(base, base + 11 * GIB)
    heap, source = heap_from_flags(maps, ["-Xmx11G"], None)
    assert source == "xmx" and heap == AddrRange(base, base + 11 * GIB)
    assert heap_from_flags(maps, ["-Xmx3G"], None) == (None, "none")
    assert heap_from_flags(maps, ["-XX:MaxRAMPercentage=50"], None) == (None, "none")
    heap, source = heap_from_flags(maps, ["-XX:MaxRAMPercentage=50"], 22 * GIB)
    assert source == "max_ram_percentage" and heap is not None and heap.start == base


def test_file_mapping_breaks_a_heap_run() -> None:
    maps = [anon(0, 1 * GIB), Mapping(1 * GIB, 2 * GIB, "r--p", "/lib/x.so", 0, 0, 0), anon(2 * GIB, 1 * GIB)]
    assert find_heap_by_size(maps, 2 * GIB, 2 * GIB) is None


def test_summary_classifies_every_region_and_ranks_mappings_by_swap() -> None:
    layout = JvmLayout(
        heap=AddrRange(0x540000000, 0x800000000),
        heap_source="jcmd",
        class_ranges=(AddrRange(0x7520C7000000, 0x752108000000),),
        code_cache=AddrRange(0x752143800000, 0x752153800000),
    )
    maps = [
        anon(0x540000000, 6 * GIB, swap=2 * GIB, rss=3 * GIB),
        anon(0x7520C8000000, 128 * MIB, swap=10 * MIB),
        anon(0x752143800000, 256 * MIB, swap=5 * MIB, perms="rwxp"),
        anon(0x7F0000000000, 1 * MIB, swap=1 * MIB),  # a thread stack: a blocked thread's SP is inside
        Mapping(0x7F1000000000, 0x7F1000100000, "r-xp", "/usr/lib/libc.so.6", MIB, MIB, 0),
        Mapping(0x7F2000000000, 0x7F2000100000, "rw-s", "/memfd:shared (deleted)", 0, 0, 7),
        Mapping(0x5600000000, 0x5600100000, "rw-p", "[heap]", 0, 0, 3),
        Mapping(0x7FFF00000000, 0x7FFF00100000, "rw-p", "[stack]", 0, 0, 0),
        anon(0x7E0000000000, 512 * MIB, swap=300 * MIB),  # malloc arena / non-class metaspace
    ]
    totals, top = summarize(maps, layout, [0x7F0000080000], top=3)
    assert set(totals) == set(Region)
    assert totals[Region.JAVA_HEAP].swap == 2 * GIB and totals[Region.JAVA_HEAP].rss == 3 * GIB
    assert totals[Region.CLASS_METADATA].swap == 10 * MIB
    assert totals[Region.CODE_CACHE].swap == 5 * MIB
    assert totals[Region.THREAD_STACK].swap == 1 * MIB and totals[Region.THREAD_STACK].mappings == 2
    assert totals[Region.FILE_MAPPED].rss == MIB
    assert totals[Region.SHMEM].swap == 7
    assert totals[Region.BRK_HEAP].swap == 3
    assert totals[Region.ANON_OTHER].swap == 300 * MIB
    assert [c.region for c in top] == [Region.JAVA_HEAP, Region.ANON_OTHER, Region.CLASS_METADATA]


def test_without_layout_nothing_is_called_java_heap() -> None:
    totals, _ = summarize([anon(0x540000000, GIB, swap=GIB)], None, [], top=5)
    assert totals[Region.JAVA_HEAP].swap == 0 and totals[Region.ANON_OTHER].swap == GIB
