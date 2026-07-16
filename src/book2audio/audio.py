"""Small, deterministic audio post-processing helpers."""

from __future__ import annotations

import math
import sys
import wave
from array import array
from pathlib import Path


def _fade_frame_counts(
    frame_count: int,
    sample_rate: int,
    fade_in_ms: float,
    fade_out_ms: float,
) -> tuple[int, int]:
    fade_in_frames = min(frame_count, max(0, round(sample_rate * fade_in_ms / 1000)))
    fade_out_frames = min(frame_count, max(0, round(sample_rate * fade_out_ms / 1000)))
    requested = fade_in_frames + fade_out_frames
    if requested > frame_count and requested:
        fade_in_frames = round(frame_count * fade_in_frames / requested)
        fade_out_frames = frame_count - fade_in_frames
    return fade_in_frames, fade_out_frames


def _half_cosine_gain(index: int, frame_count: int, fade_in: bool) -> float:
    if frame_count <= 1:
        return 0.0
    progress = index / (frame_count - 1)
    if fade_in:
        return 0.5 - 0.5 * math.cos(math.pi * progress)
    return 0.5 + 0.5 * math.cos(math.pi * progress)


def smooth_pcm16_wav_edges(
    path: Path,
    *,
    fade_in_ms: float = 10.0,
    fade_out_ms: float = 5.0,
) -> Path:
    """Apply short half-cosine fades without changing PCM WAV duration or format."""
    if fade_in_ms < 0 or fade_out_ms < 0:
        raise ValueError("fade duration cannot be negative")

    with wave.open(str(path), "rb") as wav:
        params = wav.getparams()
        if params.sampwidth != 2 or params.comptype != "NONE":
            raise ValueError(f"expected uncompressed PCM16 WAV: {path}")
        raw_frames = wav.readframes(params.nframes)

    samples = array("h")
    samples.frombytes(raw_frames)
    if sys.byteorder == "big":
        samples.byteswap()
    expected_samples = params.nframes * params.nchannels
    if len(samples) != expected_samples:
        raise ValueError(f"truncated PCM WAV: {path}")

    fade_in_frames, fade_out_frames = _fade_frame_counts(
        params.nframes,
        params.framerate,
        fade_in_ms,
        fade_out_ms,
    )
    for frame in range(fade_in_frames):
        gain = _half_cosine_gain(frame, fade_in_frames, fade_in=True)
        offset = frame * params.nchannels
        for channel in range(params.nchannels):
            samples[offset + channel] = round(samples[offset + channel] * gain)
    for frame in range(fade_out_frames):
        gain = _half_cosine_gain(frame, fade_out_frames, fade_in=False)
        offset = (params.nframes - fade_out_frames + frame) * params.nchannels
        for channel in range(params.nchannels):
            samples[offset + channel] = round(samples[offset + channel] * gain)

    if sys.byteorder == "big":
        samples.byteswap()
    temporary = path.with_name(f".{path.name}.smooth.tmp")
    try:
        with wave.open(str(temporary), "wb") as wav:
            wav.setparams(params)
            wav.writeframes(samples.tobytes())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
