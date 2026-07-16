#!/usr/bin/env python3
"""Measure the generated pacing demo without third-party Python packages."""

from __future__ import annotations

import json
import subprocess
import sys
from array import array
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
MEDIA = HERE / "voicebook_qwen_novel_paced.mp4"
OUTPUT = HERE / "media_evaluation.json"
SILENCE_THRESHOLD = 128
MIN_SILENCE_MS = 150


def run_json(command: list[str]) -> dict:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def decode_samples(sample_rate: int) -> array:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(MEDIA), "-map", "0:a:0",
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


def silence_runs(samples: array, sample_rate: int) -> list[dict]:
    minimum_frames = round(sample_rate * MIN_SILENCE_MS / 1000)
    runs = []
    start = None
    for index, sample in enumerate(samples):
        quiet = abs(sample) <= SILENCE_THRESHOLD
        if quiet and start is None:
            start = index
        elif not quiet and start is not None:
            if index - start >= minimum_frames:
                runs.append((start, index))
            start = None
    if start is not None and len(samples) - start >= minimum_frames:
        runs.append((start, len(samples)))
    return [
        {
            "start_seconds": round(start / sample_rate, 3),
            "end_seconds": round(end / sample_rate, 3),
            "duration_ms": round((end - start) * 1000 / sample_rate),
        }
        for start, end in runs
    ]


def main() -> None:
    if not MEDIA.is_file():
        raise SystemExit(f"missing media: {MEDIA}")
    probe = run_json([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_chapters",
        "-of", "json", str(MEDIA),
    ])
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    sample_rate = int(audio["sample_rate"])
    samples = decode_samples(sample_rate)
    jumps = [
        abs(samples[index] - samples[index - 1])
        for index in range(1, len(samples))
    ]
    manifest = {
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "media": MEDIA.name,
        "configured_pacing": {
            "chapter_end_pause_ms": 700,
            "title_pause_ms": 450,
            "segment_pause_ms": 250,
            "old_age_tempo": 1.15,
        },
        "media_result": {
            "duration_seconds": float(probe["format"]["duration"]),
            "codec": audio["codec_name"],
            "sample_rate_hz": sample_rate,
            "channels": audio["channels"],
            "chapter_count": len(probe.get("chapters", [])),
            "decoded_frames": len(samples),
            "max_adjacent_sample_jump": max(jumps, default=0),
            "adjacent_sample_jumps_gte_20000": sum(jump >= 20_000 for jump in jumps),
            "detected_silence_runs": silence_runs(samples, sample_rate),
        },
    }
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
