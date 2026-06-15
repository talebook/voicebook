#!/usr/bin/env python3
"""Generate Mandarin samples with Kokoro ONNX v1.1 zh and Misaki legacy IPA G2P."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro
from misaki import zh


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVAL_DIR / "samples"
MANIFEST_PATH = EVAL_DIR / "manifest.json"
PLAYLIST_PATH = EVAL_DIR / "playlist.html"

MODEL_PATH = ROOT / "models/kokoro-v1.1-zh.onnx"
VOICES_PATH = ROOT / "models/voices-v1.1-zh.bin"

VOICE = "zm_010"

STATES = {
    "weak": {
        "label": "虚弱",
        "text": "我没事……别停下，先把药箱拿过来。",
    },
    "angry": {
        "label": "愤怒",
        "text": "够了！你还想瞒我到什么时候？",
    },
    "whisper": {
        "label": "低语",
        "text": "别出声……门外有人。",
    },
}


def voice_summary() -> dict:
    voices = np.load(VOICES_PATH)
    keys = list(voices.keys())
    zh_keys = [key for key in keys if key.startswith(("zf_", "zm_"))]
    first = voices[keys[0]]
    return {
        "total_voices": len(keys),
        "zh_voices": len(zh_keys),
        "selected_voice": VOICE,
        "selected_voice_shape": list(voices[VOICE].shape),
        "selected_voice_dtype": str(voices[VOICE].dtype),
        "voice_tensor_shape_example": list(first.shape),
    }


def write_playlist(manifest: dict) -> None:
    rows = []
    for sample in manifest["samples"]:
        controls = json.dumps(sample["controls"], ensure_ascii=False)
        rows.append(
            f"""
      <tr>
        <td>{sample["state_label"]}</td>
        <td class="line">{sample["text"]}</td>
        <td><audio controls preload="metadata" src="{sample["file"]}"></audio></td>
        <td><code>{controls}</code></td>
      </tr>"""
        )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kokoro ONNX v1.1 Mandarin Samples</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .meta {{ color: #5f6368; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th, td {{ border-bottom: 1px solid #dadce0; padding: 10px 8px; text-align: left; vertical-align: middle; }}
    audio {{ width: min(480px, 100%); }}
    code {{ white-space: pre-wrap; font-size: 12px; }}
    .line {{ font-size: 17px; }}
  </style>
</head>
<body>
  <h1>Kokoro ONNX v1.1 Mandarin Samples</h1>
  <p class="meta">Generated at {manifest["updated_at"]}. Uses Misaki legacy IPA G2P and Kokoro ONNX zh v1.1.</p>
  <table>
    <thead><tr><th>State</th><th>Text</th><th>Sample</th><th>Controls</th></tr></thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    PLAYLIST_PATH.write_text(html, encoding="utf-8")


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    # kokoro-onnx's bundled vocab is IPA-based. Misaki zh version="1.1"
    # emits Zhuyin-style symbols that are filtered out by this tokenizer.
    g2p = zh.ZHG2P(version=None)
    kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))

    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "engine": "Kokoro ONNX zh v1.1",
        "model": str(MODEL_PATH.relative_to(ROOT)),
        "voices": str(VOICES_PATH.relative_to(ROOT)),
        "g2p": "misaki.zh.ZHG2P(version=None)",
        "voice_summary": voice_summary(),
        "note": "Kokoro has no instruct/emotion prompt path here; state labels only identify the input lines.",
        "samples": [],
    }

    for state, cfg in STATES.items():
        out = SAMPLE_DIR / f"{state}_kokoro_v11_{VOICE}.wav"
        phonemes, _ = g2p(cfg["text"])
        t0 = time.time()
        samples, sample_rate = kokoro.create(
            phonemes,
            voice=VOICE,
            speed=1.0,
            is_phonemes=True,
        )
        sf.write(out, samples, sample_rate)
        manifest["samples"].append(
            {
                "state": state,
                "state_label": cfg["label"],
                "text": cfg["text"],
                "phonemes": phonemes,
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "wav",
                "controls": {
                    "voice": VOICE,
                    "speed": 1.0,
                    "is_phonemes": True,
                },
                "seconds_to_generate": round(time.time() - t0, 2),
                "bytes": out.stat().st_size,
            }
        )
        print(f"[kokoro-v1.1] {state} -> {out}")

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_playlist(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
