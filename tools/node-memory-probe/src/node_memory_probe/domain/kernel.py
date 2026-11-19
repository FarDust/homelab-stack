"""Rates from cumulative kernel counters and the snapshot trigger rule."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# /proc/vmstat counters turned into per-second rates (pages or events per second).
RATE_COUNTERS = (
    "pswpin",
    "pswpout",
    "pgscan_kswapd",
    "pgscan_direct",
    "pgsteal_kswapd",
    "pgsteal_direct",
    "pgmajfault",
    "workingset_refault_anon",
    "workingset_refault_file",
)
# /proc/meminfo fields exported next to the probe's process data so one dashboard reads both at 60 s.
MEMINFO_FIELDS = (
    "MemTotal",
    "MemFree",
    "MemAvailable",
    "Cached",
    "SwapCached",
    "Active(anon)",
    "Inactive(anon)",
    "Active(file)",
    "Inactive(file)",
    "SwapTotal",
    "SwapFree",
    "Shmem",
    "Slab",
    "SReclaimable",
    "SUnreclaim",
    "AnonPages",
)


def rate(previous: int | None, current: int | None, elapsed_s: float) -> float | None:
    """Per-second increase, or None when it cannot be measured (first run, counter reset, missing counter)."""
    if previous is None or current is None or elapsed_s <= 0 or current < previous:
        return None
    return (current - previous) / elapsed_s


def counter_rates(previous: Mapping[str, int], current: Mapping[str, int], elapsed_s: float) -> dict[str, float]:
    """Rates for every counter both samples have; unmeasurable ones are left out rather than reported as 0."""
    out: dict[str, float] = {}
    for name in RATE_COUNTERS:
        value = rate(previous.get(name), current.get(name), elapsed_s)
        if value is not None:
            out[name] = value
    return out


@dataclass(frozen=True, slots=True)
class TriggerPolicy:
    swap_free_below: int
    pswpout_above: float
    swap_free_min_interval_s: float


def snapshot_reasons(
    policy: TriggerPolicy,
    swap_free: int,
    swap_total: int,
    pswpout_rate: float | None,
    now: float,
    last_swap_free_snapshot: float | None,
) -> list[str]:
    """Reasons to write a snapshot now. Swap-out bursts always count; low SwapFree at most once per interval."""
    reasons: list[str] = []
    if pswpout_rate is not None and pswpout_rate > policy.pswpout_above:
        reasons.append(f"pswpout {pswpout_rate:.0f} pages/s > {policy.pswpout_above:.0f}")
    low = swap_total > 0 and swap_free < policy.swap_free_below
    recent = last_swap_free_snapshot is not None and now - last_swap_free_snapshot < policy.swap_free_min_interval_s
    if low and not recent:
        reasons.append(f"SwapFree {swap_free / 1024**3:.2f} GiB < {policy.swap_free_below / 1024**3:.2f} GiB")
    return reasons
