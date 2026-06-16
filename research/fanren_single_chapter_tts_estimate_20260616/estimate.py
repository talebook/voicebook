#!/usr/bin/env python3
"""Estimate per-chapter CosyVoice and EdgeTTS generation time for fanren.epub."""

from __future__ import annotations

import html
import json
import math
import re
import statistics
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOK = ROOT / "book/fanren.epub"
OUT = Path(__file__).resolve().parent / "estimate.json"

TAG_RE = re.compile(r"<[^>]+>")
QUOTE_RE = re.compile(r"“([^”]+)”")
CHAPTER_RE = re.compile(r"OEBPS/Text/chapter(\d+)\.html$")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")


def chapter_sort_key(name: str) -> int:
    match = CHAPTER_RE.match(name)
    return int(match.group(1)) if match else -1


def html_to_paragraphs(raw: str) -> list[str]:
    raw = re.sub(r"</p>\s*<p[^>]*>", "\n", raw)
    raw = re.sub(r"<br\s*/?>", "\n", raw)
    text = TAG_RE.sub("", raw)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def char_count(text: str) -> int:
    return len(HAN_RE.findall(text))


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct) - 1))
    return ordered[idx]


def human(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    return f"{minutes / 60:.1f}h"


def split_default_segments(paragraphs: list[str]) -> list[str]:
    segments: list[tuple[str, str]] = []

    def push(kind: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if segments and segments[-1][0] == kind:
            sep = "" if kind == "dialogue" else "\n"
            segments[-1] = (kind, segments[-1][1] + sep + text)
        else:
            segments.append((kind, text))

    for para in paragraphs:
        pos = 0
        for match in QUOTE_RE.finditer(para):
            push("narration", para[pos : match.start()])
            push("dialogue", match.group(1))
            pos = match.end()
        push("narration", para[pos:])
    return [text for _, text in segments if char_count(text)]


def split_dialogues(text: str) -> list[str]:
    return [match.group(1).strip() for match in QUOTE_RE.finditer(text) if match.group(1).strip()]


def estimate_edge_segment_seconds(chars: int, profile: dict) -> float:
    audio_seconds = chars / profile["speech_chars_per_second"]
    return profile["request_overhead_seconds"] + audio_seconds * profile["rtf"]


def schedule_edge(segments: list[str], profile: dict, concurrency: int = 4) -> float:
    lanes = [0.0] * concurrency
    for text in sorted(segments, key=char_count, reverse=True):
        idx = min(range(concurrency), key=lanes.__getitem__)
        lanes[idx] += estimate_edge_segment_seconds(char_count(text), profile)
    return max(lanes) if lanes else 0.0


def estimate_cosy(chars: int, profile: dict) -> float:
    return chars / profile["speech_chars_per_second"] * profile["rtf"]


def describe(values: list[float]) -> dict:
    return {
        "mean_seconds": statistics.mean(values),
        "median_seconds": statistics.median(values),
        "p90_seconds": percentile(values, 0.9),
        "max_seconds": max(values),
        "mean_human": human(statistics.mean(values)),
        "median_human": human(statistics.median(values)),
        "p90_human": human(percentile(values, 0.9)),
        "max_human": human(max(values)),
    }


def select_chapter(chapters: list[dict], key: str, target: float) -> dict:
    return min(chapters, key=lambda item: abs(item[key] - target))


def main() -> int:
    edge_prior = json.loads(
        (ROOT / "research/fanren_edge_runtime_estimate_20260616/estimate.json").read_text(
            encoding="utf-8"
        )
    )
    cosy_prior = json.loads(
        (ROOT / "research/fanren_cosy_dialogue_estimate_20260615/estimate.json").read_text(
            encoding="utf-8"
        )
    )

    edge_profile = edge_prior["estimation_profiles"]["expected"]
    edge_request_median = edge_prior["edge_benchmark"]["request_seconds"]["median"]
    cosy_profile = {
        # Same planning profile used in the prior Cosy dialogue estimate.
        "speech_chars_per_second": 4.8,
        "rtf": 11.5,
        "seconds_per_char": 11.5 / 4.8,
        "source_median_rtf": cosy_prior["cosy_benchmark"]["median_rtf"],
        "source_mean_rtf": cosy_prior["cosy_benchmark"]["mean_rtf"],
    }

    chapters: list[dict] = []
    with zipfile.ZipFile(BOOK) as epub:
        names = sorted(
            [name for name in epub.namelist() if CHAPTER_RE.match(name)],
            key=chapter_sort_key,
        )
        for name in names:
            paragraphs = html_to_paragraphs(epub.read(name).decode("utf-8", errors="ignore"))
            title = paragraphs[0] if paragraphs else f"chapter {chapter_sort_key(name)}"
            body = paragraphs[1:] if paragraphs else []
            all_text = "\n".join(paragraphs)
            body_text = "\n".join(body)
            default_segments = [title, *split_default_segments(body)]
            dialogues = split_dialogues(all_text)
            han_chars = char_count(all_text)
            dialogue_han_chars = sum(char_count(text) for text in dialogues)
            edge_full = schedule_edge(default_segments, edge_profile)
            edge_dialogue = schedule_edge(dialogues, edge_profile)
            edge_request_lower = math.ceil(len(default_segments) / 4) * edge_request_median
            chapters.append(
                {
                    "chapter": chapter_sort_key(name),
                    "file": name,
                    "title": title,
                    "han_chars": han_chars,
                    "body_han_chars": char_count(body_text),
                    "dialogue_count": len(dialogues),
                    "dialogue_han_chars": dialogue_han_chars,
                    "default_segments": len(default_segments),
                    "cosy_full_expected_seconds": estimate_cosy(han_chars, cosy_profile),
                    "cosy_dialogue_expected_seconds": estimate_cosy(
                        dialogue_han_chars, cosy_profile
                    ),
                    "edge_full_expected_seconds": edge_full,
                    "edge_dialogue_expected_seconds": edge_dialogue,
                    "edge_full_request_lower_bound_seconds": edge_request_lower,
                }
            )

    for chapter in chapters:
        for key in [
            "cosy_full_expected_seconds",
            "cosy_dialogue_expected_seconds",
            "edge_full_expected_seconds",
            "edge_dialogue_expected_seconds",
            "edge_full_request_lower_bound_seconds",
        ]:
            chapter[key.replace("_seconds", "_human")] = human(chapter[key])

    full_cosy = [item["cosy_full_expected_seconds"] for item in chapters]
    full_edge = [item["edge_full_expected_seconds"] for item in chapters]
    dialogue_cosy = [item["cosy_dialogue_expected_seconds"] for item in chapters]
    dialogue_edge = [item["edge_dialogue_expected_seconds"] for item in chapters]
    chars = [item["han_chars"] for item in chapters]

    selected = {
        "mean_sized_chapter": select_chapter(chapters, "han_chars", statistics.mean(chars)),
        "median_sized_chapter": select_chapter(chapters, "han_chars", statistics.median(chars)),
        "p90_sized_chapter": select_chapter(chapters, "han_chars", percentile(chars, 0.9)),
        "longest_chapter": max(chapters, key=lambda item: item["han_chars"]),
    }

    result = {
        "created_at": "2026-06-16",
        "book": str(BOOK.relative_to(ROOT)),
        "chapter_count": len(chapters),
        "assumptions": {
            "edge": {
                "scenario": "project default narration/dialogue segmentation",
                "concurrency": 4,
                "expected_profile": edge_profile,
                "request_only_median_seconds": edge_request_median,
            },
            "cosy": {
                "scenario": "local CPU CosyVoice, expected planning profile",
                "expected_profile": cosy_profile,
            },
        },
        "chapter_distribution": {
            "han_chars": {
                "mean": statistics.mean(chars),
                "median": statistics.median(chars),
                "p90": percentile(chars, 0.9),
                "max": max(chars),
            },
            "cosy_full": describe(full_cosy),
            "edge_full": describe(full_edge),
            "cosy_dialogue_only": describe(dialogue_cosy),
            "edge_dialogue_only": describe(dialogue_edge),
        },
        "selected_chapters": selected,
        "top_10_longest_chapters": sorted(
            chapters, key=lambda item: item["han_chars"], reverse=True
        )[:10],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
