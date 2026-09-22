"""Deterministic minimum-length shot boundaries, shared by processing and display."""
import bisect
import math


MIN_SHOT_DURATION_S = 0.5


def select_shot_boundaries(boundaries, start_s, end_s, min_duration=MIN_SHOT_DURATION_S):
    """Keep stronger cuts first, with enough room on both sides of every cut.

    Removing a boundary merges adjacent intervals; it never discards video time.
    Frame timestamps are represented in microseconds to avoid floating-point
    subtraction turning an exact 0.5-second interval into a shorter one.
    A whole clip shorter than the minimum simply has no internal boundaries.
    Inputs and their dictionaries are never modified.
    """
    if not all(math.isfinite(value) for value in (start_s, end_s, min_duration)) or not 0 < min_duration or end_s <= start_s:
        raise ValueError("镜头边界必须具有有效时间范围与正的最短时长")
    start, end = round(start_s * 1_000_000), round(end_s * 1_000_000)
    minimum = max(1, round(min_duration * 1_000_000))
    candidates = []
    for boundary in boundaries:
        point = boundary["time_s"]
        if not math.isfinite(point):
            raise ValueError("镜头切点时间无效")
        tick = round(point * 1_000_000)
        if start < tick < end:
            score = boundary.get("score", 0.0)
            score = score if isinstance(score, (float, int)) and math.isfinite(score) else 0.0
            candidates.append((tick, score, boundary))
    selected, positions = [], [start, end]
    # Stable tie-breaking makes equal-strength detections reproducible.
    for tick, _, boundary in sorted(candidates, key=lambda item: (-item[1], item[0])):
        at = bisect.bisect_left(positions, tick)
        if tick - positions[at - 1] >= minimum and positions[at] - tick >= minimum:
            positions.insert(at, tick)
            selected.append(boundary)
    return sorted(selected, key=lambda item: item["time_s"])
