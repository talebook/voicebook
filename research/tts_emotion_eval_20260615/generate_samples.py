#!/usr/bin/env python3
"""Generate emotion-state TTS samples for Voicebook.

Outputs:
  samples/*.mp3  Edge TTS
  samples/*.wav  Kokoro and CosyVoice3
  manifest.json  generation metadata
  playlist.html  local browser playback page
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVAL_DIR / "samples"
MANIFEST_PATH = EVAL_DIR / "manifest.json"
PLAYLIST_PATH = EVAL_DIR / "playlist.html"

PROMPT_WAV = ROOT / "temp_cosyvoice/asset/cross_lingual_prompt.wav"

STATES = {
    "weak": {
        "label": "虚弱",
        "text": "我没事……别停下，先把药箱拿过来。",
        "edge": {"rate": "-28%", "pitch": "-8Hz", "volume": "-22%"},
        "kokoro": {"speed": 0.78},
        "cosy": {
            "speed": 0.78,
            "instruct": "You are a helpful assistant. 请用尽可能慢地语速说一句话。<|endofprompt|>",
        },
        "note": "CosyVoice3 没有官方“虚弱”指令，这里用慢速和低能量文本近似。",
    },
    "angry": {
        "label": "愤怒",
        "text": "够了！你还想瞒我到什么时候？",
        "edge": {"rate": "+18%", "pitch": "+28Hz", "volume": "+18%"},
        "kokoro": {"speed": 1.12},
        "cosy": {
            "speed": 1.08,
            "instruct": "You are a helpful assistant. 请非常生气地说一句话。<|endofprompt|>",
        },
        "note": "CosyVoice3 使用官方 anger instruct prompt。",
    },
    "whisper": {
        "label": "低语",
        "text": "别出声……门外有人。",
        "edge": {"rate": "-20%", "pitch": "-18Hz", "volume": "-35%"},
        "kokoro": {"speed": 0.84},
        "cosy": {
            "speed": 0.88,
            "instruct": "You are a helpful assistant. Please say a sentence in a very soft voice.<|endofprompt|>",
        },
        "note": "CosyVoice3 使用官方 soft voice instruct prompt。",
    },
}

ENGINE_LABELS = {
    "edge": "Edge TTS / zh-CN-YunxiNeural",
    "kokoro": "Kokoro ONNX / zm_yunxi (cmn/espeak baseline, invalid for Chinese quality)",
    "cosy": "CosyVoice3-0.5B instruct / real_male prompt",
}


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if samples.ndim > 1:
        samples = samples[:, 0]
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "states": STATS_FOR_MANIFEST,
        "samples": [],
        "failures": [],
    }


STATS_FOR_MANIFEST = {
    key: {"label": item["label"], "text": item["text"], "note": item["note"]}
    for key, item in STATES.items()
}


def save_manifest(manifest: dict) -> None:
    manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_sample(manifest: dict, sample: dict) -> None:
    manifest["samples"] = [
        item
        for item in manifest.get("samples", [])
        if not (item["engine"] == sample["engine"] and item["state"] == sample["state"])
    ]
    manifest["failures"] = [
        item
        for item in manifest.get("failures", [])
        if not (item.get("engine") == sample["engine"] and item.get("state") == sample["state"])
    ]
    manifest["samples"].append(sample)
    manifest["samples"].sort(key=lambda item: (item["state"], item["engine"]))


def add_failure(manifest: dict, engine: str, state: str, error: str) -> None:
    manifest.setdefault("failures", []).append(
        {
            "engine": engine,
            "state": state,
            "error": error,
            "time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
    )


async def generate_edge(states: list[str], manifest: dict) -> None:
    import edge_tts

    for state in states:
        cfg = STATES[state]
        out = SAMPLE_DIR / f"{state}_edge_yunxi.mp3"
        t0 = time.time()
        params = cfg["edge"]
        await edge_tts.Communicate(
            cfg["text"],
            "zh-CN-YunxiNeural",
            rate=params["rate"],
            pitch=params["pitch"],
            volume=params["volume"],
        ).save(str(out))
        upsert_sample(
            manifest,
            {
                "engine": "edge",
                "engine_label": ENGINE_LABELS["edge"],
                "state": state,
                "state_label": cfg["label"],
                "text": cfg["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "mp3",
                "controls": params,
                "seconds_to_generate": round(time.time() - t0, 2),
                "bytes": out.stat().st_size,
            },
        )
        print(f"[edge] {state} -> {out}")


def generate_kokoro(states: list[str], manifest: dict) -> None:
    from kokoro_onnx import Kokoro

    model = Kokoro(str(ROOT / "models/kokoro-v1.0.onnx"), str(ROOT / "models/voices-v1.0.bin"))
    for state in states:
        cfg = STATES[state]
        out = SAMPLE_DIR / f"{state}_kokoro_zm_yunxi.wav"
        t0 = time.time()
        controls = cfg["kokoro"]
        samples, sample_rate = model.create(
            cfg["text"],
            voice="zm_yunxi",
            speed=controls["speed"],
            lang="cmn",
        )
        write_wav(out, samples, sample_rate)
        upsert_sample(
            manifest,
            {
                "engine": "kokoro",
                "engine_label": ENGINE_LABELS["kokoro"],
                "state": state,
                "state_label": cfg["label"],
                "text": cfg["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "wav",
                "controls": {"speed": controls["speed"], "lang": "cmn"},
                "seconds_to_generate": round(time.time() - t0, 2),
                "bytes": out.stat().st_size,
            },
        )
        print(f"[kokoro] {state} -> {out}")


def generate_cosy(states: list[str], manifest: dict) -> None:
    jobs = []
    for state in states:
        cfg = STATES[state]
        jobs.append(
            {
                "state": state,
                "label": cfg["label"],
                "text": cfg["text"],
                "instruct": cfg["cosy"]["instruct"],
                "speed": cfg["cosy"]["speed"],
                "prompt_wav": str(PROMPT_WAV),
                "out": str(SAMPLE_DIR / f"{state}_cosyvoice3_real_male.wav"),
            }
        )

    job_file = EVAL_DIR / "_cosy_emotion_jobs.json"
    result_file = EVAL_DIR / "_cosy_emotion_results.json"
    job_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    if result_file.exists():
        result_file.unlink()

    cmd = [
        str(ROOT / "temp_cosyvoice/.venv/bin/python"),
        str(Path(__file__).resolve()),
        "--cosy-worker",
        "--jobs",
        str(job_file),
        "--results",
        str(result_file),
    ]
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    results = json.loads(result_file.read_text(encoding="utf-8"))

    for item in results:
        out = Path(item["file"])
        cfg = STATES[item["state"]]
        upsert_sample(
            manifest,
            {
                "engine": "cosy",
                "engine_label": ENGINE_LABELS["cosy"],
                "state": item["state"],
                "state_label": cfg["label"],
                "text": cfg["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "wav",
                "controls": {
                    "speed": cfg["cosy"]["speed"],
                    "instruct": cfg["cosy"]["instruct"],
                    "prompt_wav": str(PROMPT_WAV.relative_to(ROOT)),
                },
                "audio_duration_seconds": item["audio_duration_seconds"],
                "seconds_to_generate": item["seconds_to_generate"],
                "bytes": out.stat().st_size,
            },
        )
        print(f"[cosy] {item['state']} -> {out}")

    job_file.unlink(missing_ok=True)
    result_file.unlink(missing_ok=True)


def run_cosy_worker(jobs_path: Path, results_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "temp_cosyvoice"))
    sys.path.insert(0, str(ROOT / "temp_cosyvoice/third_party/Matcha-TTS"))

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    model_dir = ROOT / "pretrained_models/Fun-CosyVoice3-0.5B"
    t0 = time.time()
    cosyvoice = AutoModel(model_dir=str(model_dir))
    print(f"[cosy-worker] model loaded in {time.time() - t0:.1f}s")

    results = []
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    for index, job in enumerate(jobs, start=1):
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        wavs = [
            item["tts_speech"]
            for item in cosyvoice.inference_instruct2(
                job["text"],
                job["instruct"],
                job["prompt_wav"],
                stream=False,
                speed=job["speed"],
            )
        ]
        audio = torch.cat(wavs, dim=1)
        torchaudio.save(str(out), audio, cosyvoice.sample_rate)
        audio_duration = audio.shape[1] / cosyvoice.sample_rate
        elapsed = time.time() - t0
        results.append(
            {
                "state": job["state"],
                "file": str(out),
                "audio_duration_seconds": round(audio_duration, 2),
                "seconds_to_generate": round(elapsed, 2),
            }
        )
        print(f"[cosy-worker] {index}/{len(jobs)} {job['state']} audio={audio_duration:.2f}s gen={elapsed:.1f}s")

    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_playlist(manifest: dict) -> None:
    by_state: dict[str, list[dict]] = {state: [] for state in STATES}
    for sample in manifest.get("samples", []):
        by_state.setdefault(sample["state"], []).append(sample)

    state_sections = []
    for state, cfg in STATES.items():
        rows = []
        for sample in sorted(by_state.get(state, []), key=lambda item: item["engine"]):
            controls = json.dumps(sample["controls"], ensure_ascii=False)
            rows.append(
                f"""
        <tr>
          <td>{sample["engine_label"]}</td>
          <td><audio controls preload="metadata" src="{sample["file"]}"></audio></td>
          <td><code>{controls}</code></td>
        </tr>"""
            )
        state_sections.append(
            f"""
    <section>
      <h2>{cfg["label"]}</h2>
      <p class="line">{cfg["text"]}</p>
      <p class="note">{cfg["note"]}</p>
      <table>
        <thead><tr><th>Engine</th><th>Sample</th><th>Controls</th></tr></thead>
        <tbody>{''.join(rows)}
        </tbody>
      </table>
    </section>"""
        )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Voicebook TTS Emotion Samples</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    h2 {{ margin-top: 32px; }}
    .meta, .note {{ color: #5f6368; }}
    .line {{ font-size: 18px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border-bottom: 1px solid #dadce0; padding: 10px 8px; text-align: left; vertical-align: middle; }}
    audio {{ width: min(480px, 100%); }}
    code {{ white-space: pre-wrap; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>Voicebook TTS Emotion Samples</h1>
  <p class="meta">Generated at {manifest.get("updated_at", "")}. Compare each row by state.</p>
  {''.join(state_sections)}
</body>
</html>
"""
    PLAYLIST_PATH.write_text(html, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", nargs="+", choices=["edge", "kokoro", "cosy"], default=["edge", "kokoro", "cosy"])
    parser.add_argument("--states", nargs="+", choices=list(STATES), default=list(STATES))
    parser.add_argument("--cosy-worker", action="store_true")
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--results", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cosy_worker:
        if args.jobs is None or args.results is None:
            raise SystemExit("--cosy-worker requires --jobs and --results")
        run_cosy_worker(args.jobs, args.results)
        return 0

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    for engine in args.engines:
        try:
            if engine == "edge":
                asyncio.run(generate_edge(args.states, manifest))
            elif engine == "kokoro":
                generate_kokoro(args.states, manifest)
            elif engine == "cosy":
                generate_cosy(args.states, manifest)
        except Exception as exc:
            for state in args.states:
                add_failure(manifest, engine, state, repr(exc))
            print(f"[{engine}] failed: {exc}", file=sys.stderr)
            if engine != "edge":
                raise
        finally:
            save_manifest(manifest)

    write_playlist(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
