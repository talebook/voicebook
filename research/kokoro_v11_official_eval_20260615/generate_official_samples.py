#!/usr/bin/env python3
"""Generate Kokoro v1.1 zh samples with the official KPipeline path."""

from __future__ import annotations

import json
import time
from pathlib import Path

import soundfile as sf
import torch
from kokoro import KModel, KPipeline


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVAL_DIR / "samples"
MANIFEST_PATH = EVAL_DIR / "manifest.json"
PLAYLIST_PATH = EVAL_DIR / "playlist.html"

REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
SAMPLE_RATE = 24000
VOICES = ["zf_001", "zm_010"]

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


def speed_callable(len_ps: int) -> float:
    """Match the official make_zh.py short-text behavior."""
    speed = 0.8
    if len_ps <= 83:
        speed = 1.0
    elif len_ps < 183:
        speed = 1 - (len_ps - 83) / 500
    return speed * 1.1


def write_playlist(manifest: dict) -> None:
    rows = []
    for sample in manifest["samples"]:
        controls = json.dumps(sample["controls"], ensure_ascii=False)
        rows.append(
            f"""
      <tr>
        <td>{sample["state_label"]}</td>
        <td>{sample["voice"]}</td>
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
  <title>Kokoro v1.1 Official KPipeline Samples</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .meta {{ color: #5f6368; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th, td {{ border-bottom: 1px solid #dadce0; padding: 10px 8px; text-align: left; vertical-align: middle; }}
    audio {{ width: min(420px, 100%); }}
    code {{ white-space: pre-wrap; font-size: 12px; }}
    .line {{ font-size: 17px; }}
  </style>
</head>
<body>
  <h1>Kokoro v1.1 Official KPipeline Samples</h1>
  <p class="meta">Generated at {manifest["updated_at"]}. Uses repo_id={REPO_ID}, lang_code='z', en_callable, and the official speed_callable pattern.</p>
  <table>
    <thead><tr><th>State</th><th>Voice</th><th>Text</th><th>Sample</th><th>Controls</th></tr></thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    PLAYLIST_PATH.write_text(html, encoding="utf-8")


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = KModel(repo_id=REPO_ID).to(device).eval()
    en_pipeline = KPipeline(lang_code="a", repo_id=REPO_ID, model=False)

    def en_callable(text: str) -> str:
        if text == "Kokoro":
            return "kˈOkəɹO"
        if text == "Sol":
            return "sˈOl"
        return next(en_pipeline(text)).phonemes

    zh_pipeline = KPipeline(
        lang_code="z",
        repo_id=REPO_ID,
        model=model,
        en_callable=en_callable,
    )

    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "engine": "Kokoro v1.1 zh official KPipeline",
        "repo_id": REPO_ID,
        "device": device,
        "controls": {
            "lang_code": "z",
            "en_callable": True,
            "speed_callable": "official make_zh.py pattern",
        },
        "samples": [],
    }

    for voice in VOICES:
        for state, cfg in STATES.items():
            out = SAMPLE_DIR / f"{state}_kokoro_official_{voice}.wav"
            t0 = time.time()
            result = next(zh_pipeline(cfg["text"], voice=voice, speed=speed_callable))
            sf.write(out, result.audio, SAMPLE_RATE)
            manifest["samples"].append(
                {
                    "state": state,
                    "state_label": cfg["label"],
                    "voice": voice,
                    "text": cfg["text"],
                    "phonemes": result.phonemes,
                    "file": str(out.relative_to(EVAL_DIR)),
                    "format": "wav",
                    "controls": {
                        "voice": voice,
                        "speed": "speed_callable",
                        "repo_id": REPO_ID,
                        "lang_code": "z",
                    },
                    "audio_duration_seconds": round(len(result.audio) / SAMPLE_RATE, 2),
                    "seconds_to_generate": round(time.time() - t0, 2),
                    "bytes": out.stat().st_size,
                }
            )
            print(f"[kokoro-official] {voice} {state} -> {out}")

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_playlist(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
