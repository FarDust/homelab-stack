"""Thrash and leak evidence for the alert: page reads per second (CIM) and the `File` pool tag count (NT pool tags).

`Get-Counter` fails on this host (error c0000bb8), so the counter is read through WMI/CIM in process. Every failure
becomes an explicit `Unknown(reason)`; nothing here guesses a number.
"""

from __future__ import annotations

import ctypes
import struct
import sys
from collections.abc import Callable

from memory_guard.domain.errors import ProbeError
from memory_guard.domain.models import Measured, PoolDiagnostics, Reading, Unknown

CIM_QUERY = "SELECT PageReadsPersec FROM Win32_PerfFormattedData_PerfOS_Memory"
SYSTEM_POOL_TAG_INFORMATION = 22
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_ACCESS_DENIED = 0xC0000022
# Tag, PagedAllocs, PagedFrees, PagedUsed, NonPagedAllocs, NonPagedFrees, NonPagedUsed
_ENTRY = struct.Struct("<4sII4xQIIQ")
_HEADER = 8  # ULONG Count plus alignment padding
_MAX_BUFFER = 64 * 1024 * 1024
_MAX_ATTEMPTS = 5


def _cim_page_reads() -> object:
    """One `PageReadsPersec` value through pywin32 WMI; raises ProbeError when WMI cannot answer."""
    if sys.platform != "win32":
        raise ProbeError("CIM is only available on Windows")
    import pywintypes
    import win32com.client

    try:
        rows = list(win32com.client.GetObject("winmgmts:root\\cimv2").ExecQuery(CIM_QUERY))
        return rows[0].PageReadsPersec
    except (pywintypes.com_error, IndexError, AttributeError) as exc:
        raise ProbeError(f"CIM query for PageReadsPersec failed: {exc!r}") from exc


def parse_counter(value: object) -> int:
    """A counter must be a non-negative integer; anything else is a malformed reading."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ProbeError(f"malformed PageReadsPersec value {value!r}")
    try:
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("not a whole number")
            value = int(value)
        number = int(str(value).strip())
    except ValueError as exc:
        raise ProbeError(f"malformed PageReadsPersec value {value!r}") from exc
    if number < 0:
        raise ProbeError(f"negative PageReadsPersec value {number}")
    return number


def _nt_pool_tags(size: int) -> tuple[int, bytes]:
    """NtQuerySystemInformation(SystemPoolTagInformation) with a buffer of `size`.

    Returns (status, buffer); on a length mismatch the second item is the needed size as 8 little-endian bytes.
    """
    if sys.platform != "win32":
        raise ProbeError("pool tags are only available on Windows")
    buf = ctypes.create_string_buffer(size)
    needed = ctypes.c_ulong()
    status = ctypes.WinDLL("ntdll").NtQuerySystemInformation(
        SYSTEM_POOL_TAG_INFORMATION, buf, size, ctypes.byref(needed)
    )
    status &= 0xFFFFFFFF
    return status, buf.raw if status == 0 else needed.value.to_bytes(8, "little")


def file_tag_objects(query: Callable[[int], tuple[int, bytes]], tag: bytes = b"File") -> int:
    """Live non-paged allocations of one pool tag. Raises ProbeError on denial, a bad status or a malformed buffer."""
    size = 1 << 22
    for _attempt in range(_MAX_ATTEMPTS):
        status, data = query(size)
        if status == STATUS_INFO_LENGTH_MISMATCH:
            wanted = int.from_bytes(data, "little") + (1 << 20)
            if wanted > _MAX_BUFFER:
                raise ProbeError(f"pool tag table larger than {_MAX_BUFFER} bytes")
            if wanted <= size:
                # ReturnLength was missing or stale: retrying the same size can never succeed.
                raise ProbeError(f"pool tag table size request {wanted} did not grow past the buffer {size}")
            size = wanted
            continue
        if status == STATUS_ACCESS_DENIED:
            raise ProbeError("pool tags need elevation in this session (STATUS_ACCESS_DENIED)")
        if status != 0:
            raise ProbeError(f"NtQuerySystemInformation(SystemPoolTagInformation) status {status:#x}")
        break
    else:
        raise ProbeError(f"pool tag table kept growing after {_MAX_ATTEMPTS} attempts")
    if len(data) < _HEADER:
        raise ProbeError("pool tag buffer shorter than its header")
    (count,) = struct.unpack_from("<I", data, 0)
    if _HEADER + count * _ENTRY.size > len(data):
        raise ProbeError(f"pool tag buffer too short for {count} entries")
    for i in range(count):
        name, _pa, _pf, _pu, allocs, frees, _nu = _ENTRY.unpack_from(data, _HEADER + i * _ENTRY.size)
        if name == tag:
            if frees > allocs:
                raise ProbeError(f"malformed {tag!r} pool tag: {frees} frees exceed {allocs} allocations")
            return allocs - frees
    raise ProbeError(f"pool tag {tag!r} not present in the table")


class WindowsPoolDiagnostics:
    def __init__(
        self,
        page_reads: Callable[[], object] = _cim_page_reads,
        pool_query: Callable[[int], tuple[int, bytes]] = _nt_pool_tags,
    ) -> None:
        self._page_reads, self._pool_query = page_reads, pool_query

    @staticmethod
    def _reading(read: Callable[[], int]) -> Reading:
        try:
            return Measured(read())
        except ProbeError as exc:
            return Unknown(str(exc))
        except Exception as exc:
            # Contract (domain/ports.py): diagnostics never raise. An unexpected failure (a missing pywin32, a
            # ctypes error) becomes a visible Unknown(reason) so the low-memory alert is never lost with it.
            return Unknown(f"{type(exc).__name__}: {exc}")

    def __call__(self) -> PoolDiagnostics:
        return PoolDiagnostics(
            self._reading(lambda: parse_counter(self._page_reads())),
            self._reading(lambda: file_tag_objects(self._pool_query)),
        )
