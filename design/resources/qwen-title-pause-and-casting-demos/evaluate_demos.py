#!/usr/bin/env python3
"""Validate casting mappings, A/B text identity, media shape, pauses, and clicks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from array import array
from datetime import datetime
from pathlib import Path

from book2audio.script import parse_script


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "demo_evaluation.json"
SILENCE_THRESHOLD = 128
EXPECTED = {
    "old-man-and-sea-a": {"老人": "Eldric Sage"},
    "old-man-and-sea-b": {"老人": "Arthur"},
    "his-country-a": {"左小龙": "Andre", "泥巴": "Serena"},
    "his-country-b": {"左小龙": "Ethan", "泥巴": "Cherry"},
    "sky-walker-a": {"余校长": "Elias", "孙四海": "Vincent", "邓有米": "Kai"},
    "sky-walker-b": {"余校长": "Andre", "孙四海": "Elias", "邓有米": "Nofish"},
}
PAIRS = (
    ("old-man-and-sea-a", "old-man-and-sea-b"),
    ("his-country-a", "his-country-b"),
    ("sky-walker-a", "sky-walker-b"),
)


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-show_chapters", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def decode(path: Path, sample_rate: int) -> array:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "-",
        ],
        check=True,
        capture_output=True,
    )
    samples = array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def long_silences(samples: array, sample_rate: int, minimum_ms: int = 800) -> list[dict]:
    minimum_frames = round(sample_rate * minimum_ms / 1000)
    ranges = []
    start = None
    for index, sample in enumerate(samples):
        quiet = abs(sample) <= SILENCE_THRESHOLD
        if quiet and start is None:
            start = index
        elif not quiet and start is not None:
            if index - start >= minimum_frames:
                ranges.append((start, index))
            start = None
    if start is not None and len(samples) - start >= minimum_frames:
        ranges.append((start, len(samples)))
    return [
        {
            "start_seconds": round(start / sample_rate, 3),
            "duration_ms": round((end - start) * 1000 / sample_rate),
        }
        for start, end in ranges
    ]


def script_data(stem: str) -> tuple[dict, list[str], list]:
    cast, chapters = parse_script(HERE / f"{stem}.script")
    mapping = {name: override for name, (_gender, _age, override) in cast.items()}
    titles = [title for title, _segments in chapters]
    normalized_body = [
        [[tag, text] for tag, text in segments]
        for _title, segments in chapters
    ]
    return mapping, titles, normalized_body


def main() -> None:
    texts = {}
    results = []
    for stem, expected_cast in EXPECTED.items():
        mapping, script_titles, normalized_body = script_data(stem)
        assert mapping == expected_cast, (stem, mapping, expected_cast)
        texts[stem] = normalized_body

        media = HERE / f"{stem}.mp4"
        info = probe(media)
        media_titles = [chapter.get("tags", {}).get("title") for chapter in info.get("chapters", [])]
        assert media_titles == script_titles, (stem, media_titles, script_titles)
        audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
        sample_rate = int(audio["sample_rate"])
        samples = decode(media, sample_rate)
        jumps = [abs(samples[index] - samples[index - 1]) for index in range(1, len(samples))]
        silences = long_silences(samples, sample_rate)
        result = {
            "id": stem,
            "cast": mapping,
            "media": media.name,
            "bytes": media.stat().st_size,
            "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
            "duration_seconds": float(info["format"]["duration"]),
            "codec": audio["codec_name"],
            "sample_rate_hz": sample_rate,
            "channels": audio["channels"],
            "chapter_count": len(info.get("chapters", [])),
            "chapter_titles": media_titles,
            "max_adjacent_sample_jump": max(jumps, default=0),
            "adjacent_sample_jumps_gte_20000": sum(jump >= 20_000 for jump in jumps),
            "silence_runs_gte_800ms": silences,
        }
        assert result["chapter_count"] == 1, result
        assert result["adjacent_sample_jumps_gte_20000"] == 0, result
        assert silences, f"{stem} has no decoded silence long enough for the 900ms title pause"
        results.append(result)

    for left, right in PAIRS:
        assert texts[left] == texts[right], f"A/B text mismatch: {left}, {right}"

    manifest = {
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "configured_pacing": {
            "title_pause_ms": 900,
            "segment_pause_ms": 250,
            "chapter_end_pause_ms": 700,
            "old_age_tempo": 1.15,
        },
        "pair_body_text_identity": {f"{left}__{right}": True for left, right in PAIRS},
        "results": results,
    }
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
