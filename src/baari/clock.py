"""Single monotonic clock for every event timestamp in Baari.

All latency numbers are differences of values from `now_ns()`, so they never mix clocks.
"""

from __future__ import annotations

import time


def now_ns() -> int:
    """Current monotonic time in nanoseconds (time.perf_counter_ns)."""
    return time.perf_counter_ns()


def ns_to_ms(ns: int | float) -> float:
    """Convert a nanosecond duration to milliseconds."""
    return ns / 1_000_000.0


def ms_since(t0_ns: int) -> float:
    """Milliseconds elapsed since `t0_ns` (a value from `now_ns()`)."""
    return ns_to_ms(now_ns() - t0_ns)
