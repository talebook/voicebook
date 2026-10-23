"""Distinct PCM tones and independent content checks on decoded final audio."""

from __future__ import annotations

import math
import subprocess
import sys
import wave
from array import array
from pathlib import Path

SAMPLE_RATE = 24_000
MARKER_SECONDS = 0.24
LABELS = [
    label for n in (1, 2) for label in [f"标题{n}", *(f"章{n}段{i}" for i in range(4))]
]
FREQUENCIES = {label: 500 + index * 200 for index, label in enumerate(LABELS)}


def marker_pcm(label: str) -> bytes:
    frequency = FREQUENCIES[label]
    samples = array(
        "h",
        (
            round(10_000 * math.sin(2 * math.pi * frequency * frame / SAMPLE_RATE))
            for frame in range(round(SAMPLE_RATE * MARKER_SECONDS))
        ),
    )
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def write_marker(label: str, output: Path):
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(marker_pcm(label))


def validate_audio_content(audio: Path, expected: list[str]) -> dict:
    """Decode the audio itself; neither timeline text nor cache names are inputs.

    Goertzel power identifies each 20ms frame. Silence separates occurrences;
    checking occurrence durations also detects consecutive duplicate PCM.
    """
    decoded = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = array("h")
    samples.frombytes(decoded)
    if sys.byteorder != "little":
        samples.byteswap()
    frame_size = SAMPLE_RATE // 50
    coefficients = {
        label: 2 * math.cos(2 * math.pi * frequency / SAMPLE_RATE)
        for label, frequency in FREQUENCIES.items()
    }
    frames = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        energy = sum(sample * sample for sample in frame)
        label = None
        if energy > len(frame) * 400**2:
            powers = {}
            for candidate, coefficient in coefficients.items():
                first = second = 0.0
                for sample in frame:
                    value = sample + coefficient * first - second
                    second, first = first, value
                powers[candidate] = (
                    first * first + second * second - coefficient * first * second
                )
            label = max(powers, key=powers.get)
            confidence = 2 * powers[label] / (len(frame) * energy)
            if confidence <= 0.5:
                label = "unrecognized"
        frames.append((start, len(frame), label))
    occurrences = []
    for index, (start, length, label) in enumerate(frames):
        if label == "unrecognized":
            # MP3 ringing/fades can leave a partial tone in one boundary frame.
            neighbors = [
                frames[i][2] for i in (index - 1, index + 1) if 0 <= i < len(frames)
            ]
            assert any(neighbor in FREQUENCIES for neighbor in neighbors), (
                f"unrecognized audible content at {start / SAMPLE_RATE:.3f}s"
            )
            continue
        if label is not None:
            if (
                occurrences
                and occurrences[-1]["label"] == label
                and occurrences[-1]["end_frame"] == start
            ):
                occurrences[-1]["end_frame"] += length
            else:
                occurrences.append(
                    {"label": label, "start_frame": start, "end_frame": start + length}
                )
    observed = [item["label"] for item in occurrences]
    assert observed == expected, {"expected": expected, "observed": observed}
    durations = [
        round((item["end_frame"] - item["start_frame"]) / SAMPLE_RATE, 3)
        for item in occurrences
    ]
    assert all(abs(duration - MARKER_SECONDS) <= 0.08 for duration in durations), (
        durations
    )
    return {
        "expected": expected,
        "observed": observed,
        "marker_seconds": durations,
        "frequencies_hz": [FREQUENCIES[label] for label in observed],
        "verified": True,
    }
