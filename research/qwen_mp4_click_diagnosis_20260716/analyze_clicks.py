#!/usr/bin/env python3
"""Measure sample discontinuities and WAV edge levels for click diagnosis."""

from __future__ import annotations

import argparse
import math
import wave
from array import array
from pathlib import Path


def read_pcm16_mono(path: Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 mono WAV: {path}")
        rate = wav.getframerate()
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
    return rate, samples


def rms(samples: array, start: int, end: int) -> float:
    window = samples[max(0, start):min(len(samples), end)]
    if not window:
        return 0.0
    return math.sqrt(sum(value * value for value in window) / len(window))


def separated_largest_jumps(samples: array, rate: int, limit: int = 16) -> list[tuple[int, int]]:
    jumps = sorted(
        ((abs(samples[i] - samples[i - 1]), i) for i in range(1, len(samples))),
        reverse=True,
    )
    selected: list[tuple[int, int]] = []
    minimum_distance = rate // 20
    for magnitude, index in jumps:
        if all(abs(index - other_index) >= minimum_distance for _, other_index in selected):
            selected.append((magnitude, index))
            if len(selected) == limit:
                break
    return selected


def report(path: Path) -> None:
    rate, samples = read_pcm16_mono(path)
    edge = max(1, rate // 50)
    jumps = [abs(samples[index] - samples[index - 1]) for index in range(1, len(samples))]
    print(f"FILE {path}")
    print(f"duration={len(samples) / rate:.6f}s rate={rate} samples={len(samples)}")
    print(
        "edges "
        f"first={samples[0]} last={samples[-1]} "
        f"start_rms_20ms={rms(samples, 0, edge):.1f} "
        f"end_rms_20ms={rms(samples, len(samples) - edge, len(samples)):.1f}"
    )
    print(
        f"jump_counts ge_20000={sum(value >= 20_000 for value in jumps)} "
        f"ge_25000={sum(value >= 25_000 for value in jumps)} "
        f"ge_30000={sum(value >= 30_000 for value in jumps)} "
        f"maximum={max(jumps)}"
    )
    print("largest_separated_jumps:")
    context = rate // 100
    for magnitude, index in separated_largest_jumps(samples, rate):
        local_rms = rms(samples, index - context, index + context)
        score = magnitude / max(local_rms, 1.0)
        print(
            f"  t={index / rate:9.6f}s jump={magnitude:5d} "
            f"before={samples[index - 1]:6d} after={samples[index]:6d} "
            f"rms_20ms={local_rms:7.1f} score={score:6.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.wav:
        report(path)


if __name__ == "__main__":
    main()
