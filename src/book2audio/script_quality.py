"""Deterministic preparation for scripts newly built by inspect/convert."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from .script import ScriptSegment, VoicebookScript


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*")
SENTENCE_ENDS = frozenset("。！？!?；;….")
CLOSERS = frozenset("”’\"」』）)]》〉")
PAUSES = frozenset("，,、：:；;")
LIMITS = {
    "cjk": (28, 50, 80),
    "words": (14, 25, 40),
}


def _mode(value: str) -> str:
    visible = [char for char in value if not char.isspace()]
    cjk = sum(bool(CJK_RE.fullmatch(char)) for char in visible)
    return "cjk" if cjk and cjk / max(1, len(visible)) >= 0.2 else "words"


def _measure(value: str, mode: str) -> int:
    if mode == "cjk":
        return sum(not char.isspace() for char in value)
    words = WORD_RE.findall(value)
    return len(words) if words else sum(not char.isspace() for char in value)


def _trimmed_range(value: str, start: int, end: int) -> tuple[int, int]:
    while start < end and value[start].isspace():
        start += 1
    while end > start and value[end - 1].isspace():
        end -= 1
    return start, end


def _sentence_ranges(value: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(value):
        if value[index] not in SENTENCE_ENDS:
            index += 1
            continue
        end = index + 1
        while end < len(value) and value[end] in SENTENCE_ENDS | CLOSERS:
            end += 1
        left, right = _trimmed_range(value, start, end)
        if left < right:
            ranges.append((left, right))
        start = end
        index = end
    left, right = _trimmed_range(value, start, len(value))
    if left < right:
        ranges.append((left, right))
    return ranges or ([(0, len(value))] if value else [])


def _unit_boundaries(value: str, start: int, end: int, mode: str) -> list[int]:
    if mode == "cjk":
        return [index + 1 for index in range(start, end) if not value[index].isspace()]
    boundaries = [start + match.end() for match in WORD_RE.finditer(value[start:end])]
    return boundaries or [index + 1 for index in range(start, end) if not value[index].isspace()]


def _split_long_range(value: str, start: int, end: int, mode: str) -> list[tuple[int, int]]:
    minimum, target, maximum = LIMITS[mode]
    ranges: list[tuple[int, int]] = []
    while _measure(value[start:end], mode) > maximum:
        candidates = []
        for position in range(start + 1, end + 1):
            if value[position - 1] not in PAUSES:
                continue
            size = _measure(value[start:position], mode)
            if minimum <= size <= maximum:
                candidates.append((abs(size - target), position))
        if candidates:
            cut = min(candidates)[1]
        else:
            boundaries = _unit_boundaries(value, start, end, mode)
            cut = boundaries[min(maximum, len(boundaries)) - 1]
        left, right = _trimmed_range(value, start, cut)
        if left < right:
            ranges.append((left, right))
        start = cut
        while start < end and value[start].isspace():
            start += 1
    left, right = _trimmed_range(value, start, end)
    if left < right:
        ranges.append((left, right))
    return ranges


def _script_ranges(value: str) -> list[tuple[int, int]]:
    mode = _mode(value)
    minimum, target, maximum = LIMITS[mode]
    units: list[tuple[int, int]] = []
    for start, end in _sentence_ranges(value):
        units.extend(_split_long_range(value, start, end, mode))
    grouped: list[list[int]] = []
    for start, end in units:
        if not grouped:
            grouped.append([start, end])
            continue
        current = grouped[-1]
        current_size = _measure(value[current[0] : current[1]], mode)
        combined_size = _measure(value[current[0] : end], mode)
        if combined_size <= maximum and (
            current_size < minimum or abs(combined_size - target) <= abs(current_size - target)
        ):
            current[1] = end
        else:
            grouped.append([start, end])
    if len(grouped) > 1:
        tail = grouped[-1]
        previous = grouped[-2]
        if (
            _measure(value[tail[0] : tail[1]], mode) < minimum
            and _measure(value[previous[0] : tail[1]], mode) <= maximum
        ):
            previous[1] = tail[1]
            grouped.pop()
    return [(start, end) for start, end in grouped]


def _segment_locator(
    locator: dict[str, object] | None,
    text: str,
    start: int,
    end: int,
) -> tuple[dict[str, object] | None, bool]:
    if not isinstance(locator, dict):
        return None, False
    value = dict(locator)
    base_start = value.get("start_char")
    base_end = value.get("end_char")
    if not isinstance(base_start, int) or not isinstance(base_end, int) or base_end < base_start:
        return value, False
    piece = text[start:end]
    value.update(
        {
            "start_char": base_start + start,
            "end_char": base_start + end,
            "text_sha256": hashlib.sha256(piece.encode("utf-8")).hexdigest(),
        }
    )
    return value, True


def prepare_new_script(
    script: VoicebookScript,
    extraction_report: dict[str, int] | None = None,
) -> dict[str, int]:
    """Prepare an in-memory script built by inspect; never call this from generate."""

    report = {
        "version": 1,
        "chapters_before": len(script.chapters),
        "chapters_after": len(script.chapters),
        "segments_before": sum(len(chapter.segments) for chapter in script.chapters),
        "segments_after": 0,
        "removed_chapter_count": 0,
        "renamed_chapter_count": 0,
        "removed_noncontent_block_count": 0,
        "locator_unmapped_count": 0,
    }
    for key, value in (extraction_report or {}).items():
        if key in report:
            report[key] = int(value)
    if not extraction_report or "chapters_before" not in extraction_report:
        report["chapters_before"] = len(script.chapters) + report["removed_chapter_count"]
    if not extraction_report or "chapters_after" not in extraction_report:
        report["chapters_after"] = len(script.chapters)

    for chapter in script.chapters:
        prepared: list[ScriptSegment] = []
        for segment in chapter.segments:
            text = segment.text
            if not text.strip():
                continue
            for start, end in _script_ranges(text):
                piece = text[start:end]
                if not piece:
                    continue
                locator, mapped = _segment_locator(segment.locator, text, start, end)
                if not mapped:
                    report["locator_unmapped_count"] += 1
                prepared.append(replace(segment, text=piece, locator=locator))
        chapter.segments = prepared
    report["segments_after"] = sum(len(chapter.segments) for chapter in script.chapters)
    script.quality_report = report
    return report
