"""Merging of closed integer intervals.

An interval is a pair ``(start, end)`` of integers with ``start <= end``; it stands for every integer ``x`` with
``start <= x <= end``. Both ends are included, so ``(5, 5)`` is a one-point interval.
"""


def merge_intervals(intervals):
    """Merge overlapping or touching intervals.

    ``intervals`` is a list of ``(start, end)`` pairs (tuples or two-item lists) in any order; it may be empty and
    may contain duplicates or intervals nested in one another.

    Two intervals are merged into one when they overlap or touch, that is when they share at least one point:
    ``(1, 3)`` and ``(3, 5)`` become ``(1, 5)``; ``(1, 3)`` and ``(2, 9)`` become ``(1, 9)``. Intervals that share
    no point stay separate: ``(1, 3)`` and ``(4, 5)`` are two intervals. Merging repeats until no two intervals in
    the result share a point.

    Returns a new list of ``(start, end)`` tuples sorted by ``start``; the argument is left unchanged.
    Raises ``ValueError`` if any pair has ``start > end``.
    """
    pairs = [(start, end) for start, end in intervals]
    for start, end in pairs:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
    merged = []
    for start, end in pairs:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged
