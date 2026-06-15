#!/usr/bin/env python3
"""Estimate CosyVoice3 time for all quoted dialogue in book/fanren.epub."""

from __future__ import annotations

import html
import json
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


def html_to_text(raw: str) -> str:
    raw = re.sub(r"</p>\s*<p[^>]*>", "\n", raw)
    raw = re.sub(r"<br\s*/?>", "\n", raw)
    text = TAG_RE.sub("", raw)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def chapter_sort_key(name: str) -> int:
    match = CHAPTER_RE.match(name)
    return int(match.group(1)) if match else -1


def char_count(text: str) -> int:
    return len(HAN_RE.findall(text))


def load_cosy_benchmarks() -> dict:
    paths = [
        ROOT / "research/tts_engine_gender_matrix_20260615/manifest.json",
        ROOT / "research/cosy_instruct_only_eval_20260615/manifest.json",
        ROOT / "research/tts_emotion_eval_20260615/manifest.json",
    ]
    samples = []
    for path in paths:
        if not path.exists():
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for sample in manifest.get("samples", []):
            if sample.get("engine") not in {"cosy", None} and "cosy" not in sample.get("file", ""):
                continue
            duration = sample.get("audio_duration_seconds")
            elapsed = sample.get("seconds_to_generate")
            text = sample.get("text", "")
            if duration and elapsed and text:
                samples.append(
                    {
                        "file": sample.get("file"),
                        "chars": char_count(text),
                        "audio_duration_seconds": float(duration),
                        "seconds_to_generate": float(elapsed),
                        "rtf": float(elapsed) / float(duration),
                        "seconds_per_char": float(elapsed) / max(char_count(text), 1),
                    }
                )
    return {
        "samples": samples,
        "count": len(samples),
        "median_rtf": statistics.median(item["rtf"] for item in samples),
        "mean_rtf": statistics.mean(item["rtf"] for item in samples),
        "median_seconds_per_char": statistics.median(item["seconds_per_char"] for item in samples),
        "mean_seconds_per_char": statistics.mean(item["seconds_per_char"] for item in samples),
    }


def main() -> int:
    with zipfile.ZipFile(BOOK) as epub:
        names = sorted(
            [name for name in epub.namelist() if CHAPTER_RE.match(name)],
            key=chapter_sort_key,
        )
        dialogues = []
        chapter_stats = []
        total_han_chars = 0
        for name in names:
            text = html_to_text(epub.read(name).decode("utf-8", errors="ignore"))
            chapter_han = char_count(text)
            quoted = [match.group(1).strip() for match in QUOTE_RE.finditer(text)]
            quoted = [q for q in quoted if q]
            q_chars = sum(char_count(q) for q in quoted)
            total_han_chars += chapter_han
            dialogues.extend(quoted)
            chapter_stats.append(
                {
                    "file": name,
                    "chapter": chapter_sort_key(name),
                    "han_chars": chapter_han,
                    "dialogue_count": len(quoted),
                    "dialogue_han_chars": q_chars,
                }
            )

    dialogue_chars = sum(char_count(item) for item in dialogues)
    dialogue_lengths = [char_count(item) for item in dialogues]
    benchmark = load_cosy_benchmarks()

    # Chinese audiobook speech rate approximation from our short Cosy samples:
    # around 4.5-5.2 Han chars/sec. Keep estimates broad.
    audio_seconds_low = dialogue_chars / 5.2
    audio_seconds_mid = dialogue_chars / 4.8
    audio_seconds_high = dialogue_chars / 4.2

    # Recent local Cosy CPU runs cluster around RTF 10-13 for short dialogue.
    # Use a broad range because long lines may be more efficient but female prompt
    # and instruct prompts were slower in recent tests.
    estimates = {
        "optimistic": {
            "audio_seconds": audio_seconds_low,
            "rtf": 9.0,
            "wall_seconds": audio_seconds_low * 9.0,
        },
        "expected": {
            "audio_seconds": audio_seconds_mid,
            "rtf": 11.5,
            "wall_seconds": audio_seconds_mid * 11.5,
        },
        "pessimistic": {
            "audio_seconds": audio_seconds_high,
            "rtf": 14.0,
            "wall_seconds": audio_seconds_high * 14.0,
        },
        "observed_seconds_per_char_expected": {
            "seconds_per_char": benchmark["mean_seconds_per_char"],
            "wall_seconds": dialogue_chars * benchmark["mean_seconds_per_char"],
        },
        "observed_seconds_per_char_median": {
            "seconds_per_char": benchmark["median_seconds_per_char"],
            "wall_seconds": dialogue_chars * benchmark["median_seconds_per_char"],
        },
    }

    result = {
        "book": str(BOOK.relative_to(ROOT)),
        "chapter_files": len(names),
        "total_han_chars": total_han_chars,
        "dialogue_count": len(dialogues),
        "dialogue_han_chars": dialogue_chars,
        "dialogue_share_by_chars": dialogue_chars / total_han_chars,
        "dialogue_length": {
            "mean": statistics.mean(dialogue_lengths),
            "median": statistics.median(dialogue_lengths),
            "p90": statistics.quantiles(dialogue_lengths, n=10)[8],
            "max": max(dialogue_lengths),
        },
        "cosy_benchmark": benchmark,
        "estimate": estimates,
        "chapter_stats_top_dialogue_chars": sorted(
            chapter_stats, key=lambda item: item["dialogue_han_chars"], reverse=True
        )[:20],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
