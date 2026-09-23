"""Readable source times for prose, while keeping machine references intact.

This is a read-time projection: archived analyses and completion plans benefit
without rewriting their evidence IDs, snapshots, or original acceptance checks.
"""
import math
import re
from decimal import Decimal, ROUND_HALF_UP


TEXT_FIELDS = frozenset({
    "title", "description", "requirement_description", "observation", "reason",
    "impact", "missing_information", "instruction", "subject_action", "shot_scale",
    "summary", "vlog_type", "action", "start_state", "end_state", "uncertainty",
    "caption", "prompt", "continuity", "check", "human_reason", "note", "sampling_note",
    "alternative_edit", "continuity_issue",
})
TEXT_LISTS = frozenset({
    "acceptance_checks", "prerequisites", "uncertainty_reasons", "continuity_issues",
    "subjects", "quality_issues", "story_roles",
})
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PREFIX = r"(?:(?:shot|evidence)[_\s-]?ids?|(?:镜头|证据)\s*(?:id|编号)|id)\b\s*[:：=]?\s*"
QUOTE = r"[`\"'‘’“”]?"
OPEN = r"[\[(（]?"
CLOSE = r"[\])）]?"
NUMBER = r"\d+(?:\.\d+)?"
SECONDS_UNIT = r"(?:秒(?:钟)?|(?i:seconds?|s)(?![A-Za-z]))"
TIME_RANGE = re.compile(
    rf"(?<![A-Za-z0-9_.:/])(?P<start>{NUMBER})"
    rf"(?P<join>\s*(?:{SECONDS_UNIT}\s*)?(?:–|—|－|-|~|～|至|到)\s*)"
    rf"(?P<end>{NUMBER})(?P<unit>\s*{SECONDS_UNIT})"
)
TIME_SECONDS = re.compile(
    rf"(?<![A-Za-z0-9_.:/])(?P<seconds>\d+\.\d{{2,}})(?P<unit>\s*{SECONDS_UNIT})"
)
TIME_CLOCK = re.compile(
    r"(?<![A-Za-z0-9_:/.])(?:\d{1,3}:[0-5]\d:[0-5]\d|\d{1,3}:[0-5]\d)"
    r"\.\d{2,}(?![\d:.])"
)


def _bounds(item, start_key, end_key):
    start, end = item.get(start_key), item.get(end_key)
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in (start, end)):
        return None
    return (start, end) if 0 <= start < end else None


def _seconds(value):
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".")


def _clock(match):
    parts = match.group().split(":")
    seconds = sum(Decimal(part) * 60 ** index for index, part in enumerate(reversed(parts)))
    tenths = int((seconds * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    minutes, tail = divmod(tenths, 600)
    end = f"{tail // 10:02d}.{tail % 10}"
    if len(parts) == 3:
        hours, minutes = divmod(minutes, 60)
        return f"{hours:0{len(parts[0])}d}:{minutes:02d}:{end}"
    return f"{minutes:0{len(parts[0])}d}:{end}"


def readable_times(value):
    """Round explicit prose timestamps, never arbitrary decimals or source coordinates."""
    value = TIME_CLOCK.sub(_clock, value)
    value = TIME_RANGE.sub(
        lambda m: f"{_seconds(m['start'])}{m['join']}{_seconds(m['end'])}{m['unit']}", value,
    )
    return TIME_SECONDS.sub(lambda m: _seconds(m["seconds"]) + m["unit"], value)


class ReadableReferences:
    def __init__(self, shots=(), evidence=()):
        ranges = {}
        for item, start_key, end_key in [
            *((s, "start_s", "end_s") for s in shots),
            *((e, "source_start_s", "source_end_s") for e in evidence),
        ]:
            bounds = _bounds(item, start_key, end_key)
            if item.get("id") and bounds:
                ranges[str(item["id"]).lower()] = f"{_seconds(bounds[0])}–{_seconds(bounds[1])} 秒"
        self.ranges = ranges
        # Non-UUID IDs remain supported for imported history and test fixtures.
        identifiers = [re.escape(key) for key in sorted(ranges, key=len, reverse=True)]
        identifiers.append(UUID)
        self.pattern = re.compile(
            rf"(?<![A-Za-z0-9_-])(?:{PREFIX})?{OPEN}{QUOTE}(?P<id>{'|'.join(identifiers)}){QUOTE}{CLOSE}(?![A-Za-z0-9_-])",
            re.IGNORECASE,
        )
        self.unknown_named = re.compile(
            rf"(?<![A-Za-z0-9_-]){PREFIX}{OPEN}{QUOTE}[A-Za-z0-9][A-Za-z0-9_-]*{QUOTE}{CLOSE}", re.IGNORECASE,
        )

    def text(self, value):
        value = self.pattern.sub(
            lambda match: self.ranges.get(match.group("id").lower(), "对应片段（时间待核实）"), value,
        )
        # Unknown references never borrow a nearby shot's time and imply false precision.
        return readable_times(self.unknown_named.sub("对应片段（时间待核实）", value))

    def payload(self, value):
        if isinstance(value, list):
            return [self.payload(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in TEXT_FIELDS and isinstance(item, str):
                result[key] = self.text(item)
            elif key in TEXT_LISTS and isinstance(item, list):
                result[key] = [self.text(text) if isinstance(text, str) else self.payload(text) for text in item]
            else:
                result[key] = self.payload(item)
        return result
