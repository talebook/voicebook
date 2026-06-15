#!/usr/bin/env python3
"""Generate CosyVoice3 emotion-state samples using instruct prompts only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


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
        "instruct": "You are a helpful assistant. 请用虚弱、气息不足、带一点停顿的状态说这句话。<|endofprompt|>",
    },
    "angry": {
        "label": "愤怒",
        "text": "够了！你还想瞒我到什么时候？",
        "instruct": "You are a helpful assistant. 请用愤怒、压抑不住情绪的语气说这句话。<|endofprompt|>",
    },
    "whisper": {
        "label": "低语",
        "text": "别出声……门外有人。",
        "instruct": "You are a helpful assistant. 请压低声音，用低声耳语、紧张克制的语气说这句话。<|endofprompt|>",
    },
}


def build_jobs(states: list[str]) -> list[dict]:
    jobs = []
    for state in states:
        cfg = STATES[state]
        jobs.append(
            {
                "state": state,
                "label": cfg["label"],
                "text": cfg["text"],
                "instruct": cfg["instruct"],
                "prompt_wav": str(PROMPT_WAV),
                "out": str(SAMPLE_DIR / f"{state}_cosyvoice3_instruct_only.wav"),
            }
        )
    return jobs


def run_worker(jobs_path: Path, results_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "temp_cosyvoice"))
    sys.path.insert(0, str(ROOT / "temp_cosyvoice/third_party/Matcha-TTS"))

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    model_dir = ROOT / "pretrained_models/Fun-CosyVoice3-0.5B"
    t0 = time.time()
    cosyvoice = AutoModel(model_dir=str(model_dir))
    print(f"[worker] model loaded in {time.time() - t0:.1f}s")

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
                "bytes": out.stat().st_size,
            }
        )
        print(f"[worker] {index}/{len(jobs)} {job['state']} audio={audio_duration:.2f}s gen={elapsed:.1f}s")

    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
  <title>CosyVoice3 Instruct-Only Emotion Samples</title>
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
  <h1>CosyVoice3 Instruct-Only Emotion Samples</h1>
  <p class="meta">Generated at {manifest["updated_at"]}. No speed parameter was passed; samples use instruct prompts only.</p>
  <table>
    <thead><tr><th>State</th><th>Text</th><th>Sample</th><th>Controls</th></tr></thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    PLAYLIST_PATH.write_text(html, encoding="utf-8")


def generate(states: list[str]) -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(states)
    job_file = EVAL_DIR / "_cosy_instruct_jobs.json"
    result_file = EVAL_DIR / "_cosy_instruct_results.json"
    job_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    result_file.unlink(missing_ok=True)

    cmd = [
        str(ROOT / "temp_cosyvoice/.venv/bin/python"),
        str(Path(__file__).resolve()),
        "--worker",
        "--jobs",
        str(job_file),
        "--results",
        str(result_file),
    ]
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    results = json.loads(result_file.read_text(encoding="utf-8"))

    by_state = {item["state"]: item for item in results}
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "engine": "CosyVoice3-0.5B instruct / real_male prompt",
        "prompt_wav": str(PROMPT_WAV.relative_to(ROOT)),
        "note": "No speed parameter is passed to inference_instruct2; CosyVoice3 uses its default speed=1.0.",
        "samples": [],
    }
    for state in states:
        cfg = STATES[state]
        result = by_state[state]
        out = Path(result["file"])
        manifest["samples"].append(
            {
                "state": state,
                "state_label": cfg["label"],
                "text": cfg["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "wav",
                "controls": {
                    "instruct": cfg["instruct"],
                    "prompt_wav": str(PROMPT_WAV.relative_to(ROOT)),
                },
                "audio_duration_seconds": result["audio_duration_seconds"],
                "seconds_to_generate": result["seconds_to_generate"],
                "bytes": result["bytes"],
            }
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_playlist(manifest)
    job_file.unlink(missing_ok=True)
    result_file.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", nargs="+", choices=list(STATES), default=list(STATES))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--results", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.jobs is None or args.results is None:
            raise SystemExit("--worker requires --jobs and --results")
        run_worker(args.jobs, args.results)
        return 0
    generate(args.states)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
