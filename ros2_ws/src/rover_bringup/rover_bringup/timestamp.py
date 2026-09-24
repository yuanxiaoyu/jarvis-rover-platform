from __future__ import annotations


NANOSECONDS_PER_SECOND = 1_000_000_000


def normalize_stamp(source_ns: int, now_ns: int, max_skew_ns: int) -> tuple[int, bool]:
    """Replace a sensor timestamp only when it is too far from ROS wall time."""
    if max_skew_ns < 0:
        raise ValueError("max_skew_ns must be non-negative")
    if abs(now_ns - source_ns) <= max_skew_ns:
        return source_ns, False
    return now_ns, True
