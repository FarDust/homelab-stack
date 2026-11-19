"""Find a JVM's heap, class metadata and code cache ranges, from jcmd when allowed, from its flags otherwise."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from node_memory_probe.domain.models import AddrRange, JvmLayout, Mapping, ProcessBrief
from node_memory_probe.domain.ports import JcmdError, JvmTool
from node_memory_probe.domain.regions import (
    JcmdParseError,
    heap_from_flags,
    parse_class_ranges,
    parse_code_cache,
    parse_heap_info,
)


def is_jvm(brief: ProcessBrief, args: Sequence[str]) -> bool:
    return brief.comm == "java" or (bool(args) and args[0].rsplit("/", 1)[-1] == "java")


def _ranges_to_state(ranges: Sequence[AddrRange]) -> list[list[int]]:
    return [[r.start, r.end] for r in ranges]


def _ranges_from_state(raw: Any) -> tuple[AddrRange, ...]:
    return tuple(AddrRange(int(a), int(b)) for a, b in raw)


def static_ranges(
    tool: JvmTool, brief: ProcessBrief, cache: dict[str, Any], errors: list[str]
) -> tuple[tuple[AddrRange, ...], AddrRange | None]:
    """Class metadata and code cache ranges never move during a JVM's life, so jcmd is asked once per process.

    `cache` is the probe state's `jvm_ranges` map, keyed by pid and start time so a reused pid is asked again.
    """
    key = f"{brief.pid}:{brief.start_ticks}"
    if key in cache:
        entry = cache[key]
        code = entry["code_cache"]
        return _ranges_from_state(entry["class_ranges"]), AddrRange(*code) if code else None
    class_ranges: tuple[AddrRange, ...] = ()
    code: AddrRange | None = None
    complete = True
    try:
        class_ranges = parse_class_ranges(tool.run(brief, "VM.info"))
    except (JcmdError, JcmdParseError) as exc:
        errors.append(f"VM.info: {exc}")
        complete = False
    try:
        code = parse_code_cache(tool.run(brief, "Compiler.codecache"))
    except (JcmdError, JcmdParseError) as exc:
        errors.append(f"Compiler.codecache: {exc}")
        complete = False
    if complete:  # a failed answer is asked again next run instead of being cached as "no ranges"
        cache[key] = {
            "class_ranges": _ranges_to_state(class_ranges),
            "code_cache": [code.start, code.end] if code else None,
        }
    return class_ranges, code


def layout_with_jcmd(
    tool: JvmTool,
    brief: ProcessBrief,
    mappings: Sequence[Mapping],
    args: Sequence[str],
    memory_limit: int | None,
    cache: dict[str, Any],
    errors: list[str],
) -> tuple[JvmLayout, bool]:
    """Layout for a JVM the operator allowed jcmd on; returns it and whether GC.heap_info answered."""
    class_ranges, code = static_ranges(tool, brief, cache, errors)
    try:
        info = parse_heap_info(tool.run(brief, "GC.heap_info"))
    except (JcmdError, JcmdParseError) as exc:
        errors.append(f"GC.heap_info: {exc}")
        heap, source = heap_from_flags(mappings, args, memory_limit)
        return JvmLayout(heap, source, class_ranges, code), False
    return JvmLayout(info.reserved, "jcmd", class_ranges, code, info), True


def layout_from_flags(mappings: Sequence[Mapping], args: Sequence[str], memory_limit: int | None) -> JvmLayout:
    heap, source = heap_from_flags(mappings, args, memory_limit)
    return JvmLayout(heap, source)
