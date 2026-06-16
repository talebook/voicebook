#!/usr/bin/env python3
"""Estimate EdgeTTS runtime for book/fanren.epub.

The estimate is based on current project segmentation and the EdgeTTS timings
already measured in prior local research folders. It does not call the Edge
service.
"""

from __future__ import annotations

import html
import json
import math
import re
import statistics
import subprocess
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
    # Keep this in sync with the prior CosyVoice estimate so book/dialogue
    # counts remain comparable across engines.
    raw = re.sub(r"</p>\s*<p[^>]*>", "\n", raw)
    raw = re.sub(r"<br\s*/?>", "\n", raw)
    text = TAG_RE.sub("", raw)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def char_count(text: str) -> int:
    return len(HAN_RE.findall(text))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * pct) - 1))
    return ordered[idx]


def probe_duration_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    data = json.loads(result.stdout)
    duration = data.get("format", {}).get("duration")
    return float(duration) if duration else None


def load_edge_benchmarks() -> dict:
    paths = [
        ROOT / "research/tts_engine_gender_matrix_20260615/manifest.json",
        ROOT / "research/tts_emotion_eval_20260615/manifest.json",
    ]
    samples = []
    for path in paths:
        if not path.exists():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for sample in manifest.get("samples", []):
            if sample.get("engine") != "edge":
                continue
            elapsed = sample.get("seconds_to_generate")
            text = sample.get("text", "")
            rel_file = sample.get("file", "")
            if not elapsed or not text or not rel_file:
                continue
            audio_path = path.parent / rel_file
            duration = sample.get("audio_duration_seconds") or probe_duration_seconds(audio_path)
            chars = char_count(text)
            item = {
                "source": str(path.relative_to(ROOT)),
                "file": rel_file,
                "chars": chars,
                "seconds_to_generate": float(elapsed),
                "seconds_per_char": float(elapsed) / max(chars, 1),
                "bytes": sample.get("bytes"),
            }
            if duration:
                item["audio_duration_seconds"] = float(duration)
                item["rtf"] = float(elapsed) / float(duration)
                item["chars_per_audio_second"] = chars / float(duration)
            samples.append(item)

    elapsed_values = [item["seconds_to_generate"] for item in samples]
    rtf_values = [item["rtf"] for item in samples if "rtf" in item]
    cps_values = [item["chars_per_audio_second"] for item in samples if "chars_per_audio_second" in item]
    return {
        "samples": samples,
        "count": len(samples),
        "request_seconds": {
            "mean": statistics.mean(elapsed_values),
            "median": statistics.median(elapsed_values),
            "p90": percentile(elapsed_values, 0.9),
            "min": min(elapsed_values),
            "max": max(elapsed_values),
        },
        "rtf": {
            "mean": statistics.mean(rtf_values) if rtf_values else None,
            "median": statistics.median(rtf_values) if rtf_values else None,
            "p90": percentile(rtf_values, 0.9) if rtf_values else None,
        },
        "chars_per_audio_second": {
            "mean": statistics.mean(cps_values) if cps_values else None,
            "median": statistics.median(cps_values) if cps_values else None,
        },
    }


def split_default_segments(paragraphs: list[str]) -> list[str]:
    """Mirror src/book2audio/parser.py split_segments plus chapter title handled elsewhere."""
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


def split_granular_segments(paragraphs: list[str]) -> list[str]:
    """Paragraph-level quote split, before same-voice merging."""
    segments: list[str] = []
    for para in paragraphs:
        pos = 0
        for match in QUOTE_RE.finditer(para):
            pre = para[pos : match.start()].strip()
            if char_count(pre):
                segments.append(pre)
            quote = match.group(1).strip()
            if char_count(quote):
                segments.append(quote)
            pos = match.end()
        tail = para[pos:].strip()
        if char_count(tail):
            segments.append(tail)
    return segments


def split_dialogues(paragraphs: list[str]) -> list[str]:
    text = "\n".join(paragraphs)
    return [match.group(1).strip() for match in QUOTE_RE.finditer(text) if match.group(1).strip()]


def split_fixed_size_chunks(paragraphs: list[str], chunk_han_chars: int = 900) -> list[str]:
    """Single-narrator chunking estimate to reduce Edge request overhead."""
    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for para in paragraphs:
        n = char_count(para)
        if current and current_chars + n > chunk_han_chars:
            chunks.append("\n".join(current))
            current = []
            current_chars = 0
        if n > chunk_han_chars:
            buf = []
            buf_chars = 0
            for ch in para:
                buf.append(ch)
                if HAN_RE.match(ch):
                    buf_chars += 1
                if buf_chars >= chunk_han_chars:
                    chunks.append("".join(buf))
                    buf = []
                    buf_chars = 0
            if buf:
                current.append("".join(buf))
                current_chars += buf_chars
            continue
        current.append(para)
        current_chars += n
    if current:
        chunks.append("\n".join(current))
    return [item for item in chunks if char_count(item)]


def estimate_segment_seconds(chars: int, profile: dict) -> float:
    audio_seconds = chars / profile["speech_chars_per_second"]
    return profile["request_overhead_seconds"] + audio_seconds * profile["rtf"]


def schedule_seconds_by_chapter(chapter_segments: list[list[str]], profile: dict, concurrency: int) -> float:
    total = 0.0
    for segments in chapter_segments:
        lanes = [0.0] * concurrency
        for text in sorted(segments, key=char_count, reverse=True):
            i = min(range(concurrency), key=lanes.__getitem__)
            lanes[i] += estimate_segment_seconds(char_count(text), profile)
        total += max(lanes) if lanes else 0.0
    return total


def seconds_to_human(seconds: float) -> str:
    hours = seconds / 3600
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def summarize_segments(chapter_segments: list[list[str]]) -> dict:
    lengths = [char_count(text) for segments in chapter_segments for text in segments]
    return {
        "segments": len(lengths),
        "han_chars": sum(lengths),
        "mean_han_chars": statistics.mean(lengths) if lengths else 0,
        "median_han_chars": statistics.median(lengths) if lengths else 0,
        "p90_han_chars": percentile(lengths, 0.9),
        "max_han_chars": max(lengths) if lengths else 0,
    }


def main() -> int:
    with zipfile.ZipFile(BOOK) as epub:
        names = sorted(
            [name for name in epub.namelist() if CHAPTER_RE.match(name)],
            key=chapter_sort_key,
        )
        chapters: list[dict] = []
        all_paragraphs: list[str] = []
        for name in names:
            raw = epub.read(name).decode("utf-8", errors="ignore")
            paragraphs = html_to_paragraphs(raw)
            all_paragraphs.extend(paragraphs)
            title = paragraphs[0] if paragraphs else f"chapter {chapter_sort_key(name)}"
            body = paragraphs[1:] if paragraphs else []
            chapters.append(
                {
                    "file": name,
                    "chapter": chapter_sort_key(name),
                    "title": title,
                    "paragraphs": body,
                    "all_text": "\n".join(paragraphs),
                }
            )

    default_by_chapter = [
        [chapter["title"], *split_default_segments(chapter["paragraphs"])] for chapter in chapters
    ]
    granular_by_chapter = [
        [chapter["title"], *split_granular_segments(chapter["paragraphs"])] for chapter in chapters
    ]
    dialogue_by_chapter = [split_dialogues([chapter["all_text"]]) for chapter in chapters]
    chunked_by_chapter = [
        [chapter["title"], *split_fixed_size_chunks(chapter["paragraphs"])] for chapter in chapters
    ]

    benchmark = load_edge_benchmarks()
    observed_rtf = benchmark["rtf"]["median"] or 0.38
    observed_cps = benchmark["chars_per_audio_second"]["median"] or 3.0

    profiles = {
        "optimistic": {
            "speech_chars_per_second": 4.8,
            "rtf": min(0.28, observed_rtf),
            "request_overhead_seconds": 0.65,
        },
        "expected": {
            "speech_chars_per_second": 4.2,
            "rtf": max(0.34, observed_rtf),
            "request_overhead_seconds": 0.85,
        },
        "conservative": {
            "speech_chars_per_second": min(3.6, observed_cps),
            "rtf": max(0.50, benchmark["rtf"]["p90"] or 0.50),
            "request_overhead_seconds": 1.15,
        },
    }

    scenarios = {
        "dialogue_only_each_quote": dialogue_by_chapter,
        "project_default_two_voice": default_by_chapter,
        "granular_multivoice_upper_bound": granular_by_chapter,
        "single_narrator_chunk_900_han": chunked_by_chapter,
    }

    estimates = {}
    for scenario, chapter_segments in scenarios.items():
        scenario_estimates = {}
        lower_bound_serial = sum(
            len(segments) * benchmark["request_seconds"]["median"] for segments in chapter_segments
        )
        lower_bound_concurrent = sum(
            math.ceil(len(segments) / 4) * benchmark["request_seconds"]["median"]
            for segments in chapter_segments
        )
        for profile_name, profile in profiles.items():
            serial_seconds = schedule_seconds_by_chapter(chapter_segments, profile, 1)
            concurrent_seconds = schedule_seconds_by_chapter(chapter_segments, profile, 4)
            scenario_estimates[profile_name] = {
                "serial_seconds": round(serial_seconds, 2),
                "serial_human": seconds_to_human(serial_seconds),
                "concurrency_4_seconds": round(concurrent_seconds, 2),
                "concurrency_4_human": seconds_to_human(concurrent_seconds),
            }
        estimates[scenario] = {
            "segment_stats": summarize_segments(chapter_segments),
            "request_only_lower_bound": {
                "serial_seconds": round(lower_bound_serial, 2),
                "serial_human": seconds_to_human(lower_bound_serial),
                "concurrency_4_seconds": round(lower_bound_concurrent, 2),
                "concurrency_4_human": seconds_to_human(lower_bound_concurrent),
            },
            "runtime": scenario_estimates,
        }

    total_han_chars = sum(char_count(p) for p in all_paragraphs)
    dialogue_lengths = [char_count(text) for segments in dialogue_by_chapter for text in segments]
    result = {
        "created_at": "2026-06-16",
        "book": str(BOOK.relative_to(ROOT)),
        "chapter_files": len(chapters),
        "paragraphs": sum(len(chapter["paragraphs"]) for chapter in chapters),
        "total_han_chars": total_han_chars,
        "dialogue_count": sum(len(segments) for segments in dialogue_by_chapter),
        "dialogue_han_chars": sum(dialogue_lengths),
        "dialogue_share_by_chars": sum(dialogue_lengths) / total_han_chars,
        "dialogue_length": {
            "mean": statistics.mean(dialogue_lengths),
            "median": statistics.median(dialogue_lengths),
            "p90": percentile(dialogue_lengths, 0.9),
            "max": max(dialogue_lengths),
        },
        "edge_benchmark": benchmark,
        "estimation_profiles": profiles,
        "concurrency": 4,
        "estimates": estimates,
        "notes": [
            "EdgeTTS is a cloud service; wall time varies with network latency and throttling.",
            "project_default_two_voice follows src/book2audio/parser.py-style narration/dialogue merging.",
            "granular_multivoice_upper_bound splits every paragraph around every quote before same-speaker merging.",
            "single_narrator_chunk_900_han estimates a single-narrator audiobook with large text chunks.",
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
