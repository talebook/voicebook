#!/usr/bin/env python3
"""Generate a gender/state TTS matrix across the current candidate engines."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVAL_DIR / "samples"
MANIFEST_PATH = EVAL_DIR / "manifest.json"
MATRIX_PATH = EVAL_DIR / "matrix.html"

KOKORO_ONNX_MODEL = ROOT / "models/kokoro-v1.1-zh.onnx"
KOKORO_ONNX_VOICES = ROOT / "models/voices-v1.1-zh.bin"
KOKORO_REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"

STATES = {
    "weak": {
        "label": "虚弱",
        "text": "我没事……别停下，先把药箱拿过来。",
        "edge": {"rate": "-28%", "pitch": "-8Hz", "volume": "-22%"},
        "instruct": "You are a helpful assistant. 请用虚弱、气息不足、带一点停顿的状态说这句话。<|endofprompt|>",
    },
    "angry": {
        "label": "愤怒",
        "text": "够了！你还想瞒我到什么时候？",
        "edge": {"rate": "+18%", "pitch": "+28Hz", "volume": "+18%"},
        "instruct": "You are a helpful assistant. 请用愤怒、压抑不住情绪的语气说这句话。<|endofprompt|>",
    },
    "whisper": {
        "label": "低语",
        "text": "别出声……门外有人。",
        "edge": {"rate": "-20%", "pitch": "-18Hz", "volume": "-35%"},
        "instruct": "You are a helpful assistant. 请压低声音，用低声耳语、紧张克制的语气说这句话。<|endofprompt|>",
    },
}

GENDERS = {
    "male": {
        "label": "男",
        "edge_voice": "zh-CN-YunxiNeural",
        "kokoro_voice": "zm_010",
        "cosy_prompt_wav": ROOT / "temp_cosyvoice/asset/cross_lingual_prompt.wav",
        "cosy_voice_label": "real_male",
    },
    "female": {
        "label": "女",
        "edge_voice": "zh-CN-XiaoxiaoNeural",
        "kokoro_voice": "zf_001",
        "cosy_prompt_wav": ROOT / "temp_cosyvoice/asset/zero_shot_prompt.wav",
        "cosy_voice_label": "real_female",
    },
}

ENGINE_LABELS = {
    "kokoro": "Kokoro official KPipeline",
    "kokoro_onnx": "Kokoro ONNX v1.1 zh",
    "cosy": "CosyVoice3 instruct",
    "edge": "Edge TTS",
}


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, sample_rate)


def base_manifest() -> dict:
    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "states": {key: {"label": value["label"], "text": value["text"]} for key, value in STATES.items()},
        "genders": {key: {"label": value["label"]} for key, value in GENDERS.items()},
        "samples": [],
        "failures": [],
    }


def upsert_sample(manifest: dict, sample: dict) -> None:
    manifest["samples"] = [
        item
        for item in manifest["samples"]
        if not (
            item["engine"] == sample["engine"]
            and item["gender"] == sample["gender"]
            and item["state"] == sample["state"]
        )
    ]
    manifest["samples"].append(sample)
    manifest["samples"].sort(key=lambda item: (item["engine"], item["gender"], item["state"]))
    manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")


def add_failure(manifest: dict, engine: str, gender: str, state: str, error: str) -> None:
    manifest["failures"].append(
        {
            "engine": engine,
            "gender": gender,
            "state": state,
            "error": error,
            "time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
    )


async def generate_edge(manifest: dict) -> None:
    import edge_tts

    for gender, gender_cfg in GENDERS.items():
        for state, state_cfg in STATES.items():
            out = SAMPLE_DIR / f"edge_{gender}_{state}.mp3"
            t0 = time.time()
            params = state_cfg["edge"]
            try:
                await edge_tts.Communicate(
                    state_cfg["text"],
                    gender_cfg["edge_voice"],
                    rate=params["rate"],
                    pitch=params["pitch"],
                    volume=params["volume"],
                ).save(str(out))
                upsert_sample(
                    manifest,
                    {
                        "engine": "edge",
                        "engine_label": ENGINE_LABELS["edge"],
                        "gender": gender,
                        "gender_label": gender_cfg["label"],
                        "state": state,
                        "state_label": state_cfg["label"],
                        "text": state_cfg["text"],
                        "file": str(out.relative_to(EVAL_DIR)),
                        "format": "mp3",
                        "controls": {"voice": gender_cfg["edge_voice"], **params},
                        "seconds_to_generate": round(time.time() - t0, 2),
                        "bytes": out.stat().st_size,
                    },
                )
                print(f"[edge] {gender}/{state} -> {out}")
            except Exception as exc:
                add_failure(manifest, "edge", gender, state, repr(exc))
                print(f"[edge] failed {gender}/{state}: {exc}", file=sys.stderr)


def official_speed_callable(len_ps: int) -> float:
    speed = 0.8
    if len_ps <= 83:
        speed = 1.0
    elif len_ps < 183:
        speed = 1 - (len_ps - 83) / 500
    return speed * 1.1


def generate_kokoro(manifest: dict) -> None:
    import torch
    from kokoro import KModel, KPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = KModel(repo_id=KOKORO_REPO_ID).to(device).eval()
    en_pipeline = KPipeline(lang_code="a", repo_id=KOKORO_REPO_ID, model=False)

    def en_callable(text: str) -> str:
        if text == "Kokoro":
            return "kˈOkəɹO"
        if text == "Sol":
            return "sˈOl"
        return next(en_pipeline(text)).phonemes

    zh_pipeline = KPipeline(lang_code="z", repo_id=KOKORO_REPO_ID, model=model, en_callable=en_callable)

    for gender, gender_cfg in GENDERS.items():
        voice = gender_cfg["kokoro_voice"]
        for state, state_cfg in STATES.items():
            out = SAMPLE_DIR / f"kokoro_{gender}_{state}.wav"
            t0 = time.time()
            result = next(zh_pipeline(state_cfg["text"], voice=voice, speed=official_speed_callable))
            write_wav(out, result.audio, 24000)
            upsert_sample(
                manifest,
                {
                    "engine": "kokoro",
                    "engine_label": ENGINE_LABELS["kokoro"],
                    "gender": gender,
                    "gender_label": gender_cfg["label"],
                    "state": state,
                    "state_label": state_cfg["label"],
                    "text": state_cfg["text"],
                    "file": str(out.relative_to(EVAL_DIR)),
                    "format": "wav",
                    "controls": {
                        "repo_id": KOKORO_REPO_ID,
                        "voice": voice,
                        "lang_code": "z",
                        "speed": "official speed_callable",
                    },
                    "audio_duration_seconds": round(len(result.audio) / 24000, 2),
                    "seconds_to_generate": round(time.time() - t0, 2),
                    "bytes": out.stat().st_size,
                },
            )
            print(f"[kokoro] {gender}/{state} -> {out}")


def generate_kokoro_onnx(manifest: dict) -> None:
    from kokoro_onnx import Kokoro
    from misaki import zh

    g2p = zh.ZHG2P(version=None)
    kokoro = Kokoro(str(KOKORO_ONNX_MODEL), str(KOKORO_ONNX_VOICES))
    for gender, gender_cfg in GENDERS.items():
        voice = gender_cfg["kokoro_voice"]
        for state, state_cfg in STATES.items():
            out = SAMPLE_DIR / f"kokoro_onnx_{gender}_{state}.wav"
            phonemes, _ = g2p(state_cfg["text"])
            t0 = time.time()
            samples, sample_rate = kokoro.create(phonemes, voice=voice, speed=1.0, is_phonemes=True)
            write_wav(out, samples, sample_rate)
            upsert_sample(
                manifest,
                {
                    "engine": "kokoro_onnx",
                    "engine_label": ENGINE_LABELS["kokoro_onnx"],
                    "gender": gender,
                    "gender_label": gender_cfg["label"],
                    "state": state,
                    "state_label": state_cfg["label"],
                    "text": state_cfg["text"],
                    "file": str(out.relative_to(EVAL_DIR)),
                    "format": "wav",
                    "controls": {
                        "model": str(KOKORO_ONNX_MODEL.relative_to(ROOT)),
                        "voices": str(KOKORO_ONNX_VOICES.relative_to(ROOT)),
                        "voice": voice,
                        "g2p": "misaki.zh.ZHG2P(version=None)",
                        "speed": 1.0,
                    },
                    "audio_duration_seconds": round(len(samples) / sample_rate, 2),
                    "seconds_to_generate": round(time.time() - t0, 2),
                    "bytes": out.stat().st_size,
                },
            )
            print(f"[kokoro-onnx] {gender}/{state} -> {out}")


def generate_cosy(manifest: dict) -> None:
    jobs = []
    for gender, gender_cfg in GENDERS.items():
        for state, state_cfg in STATES.items():
            jobs.append(
                {
                    "gender": gender,
                    "gender_label": gender_cfg["label"],
                    "state": state,
                    "state_label": state_cfg["label"],
                    "text": state_cfg["text"],
                    "instruct": state_cfg["instruct"],
                    "prompt_wav": str(gender_cfg["cosy_prompt_wav"]),
                    "voice_label": gender_cfg["cosy_voice_label"],
                    "out": str(SAMPLE_DIR / f"cosy_{gender}_{state}.wav"),
                }
            )

    job_file = EVAL_DIR / "_cosy_jobs.json"
    result_file = EVAL_DIR / "_cosy_results.json"
    job_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    result_file.unlink(missing_ok=True)

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
    by_key = {(item["gender"], item["state"]): item for item in results}

    for job in jobs:
        item = by_key[(job["gender"], job["state"])]
        out = Path(item["file"])
        upsert_sample(
            manifest,
            {
                "engine": "cosy",
                "engine_label": ENGINE_LABELS["cosy"],
                "gender": job["gender"],
                "gender_label": job["gender_label"],
                "state": job["state"],
                "state_label": job["state_label"],
                "text": job["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "format": "wav",
                "controls": {
                    "voice": job["voice_label"],
                    "prompt_wav": str(Path(job["prompt_wav"]).relative_to(ROOT)),
                    "instruct": job["instruct"],
                },
                "audio_duration_seconds": item["audio_duration_seconds"],
                "seconds_to_generate": item["seconds_to_generate"],
                "bytes": out.stat().st_size,
            },
        )
        print(f"[cosy] {job['gender']}/{job['state']} -> {out}")

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
            )
        ]
        audio = torch.cat(wavs, dim=1)
        torchaudio.save(str(out), audio, cosyvoice.sample_rate)
        elapsed = time.time() - t0
        audio_duration = audio.shape[1] / cosyvoice.sample_rate
        results.append(
            {
                "gender": job["gender"],
                "state": job["state"],
                "file": str(out),
                "audio_duration_seconds": round(audio_duration, 2),
                "seconds_to_generate": round(elapsed, 2),
            }
        )
        print(
            f"[cosy-worker] {index}/{len(jobs)} {job['gender']}/{job['state']} "
            f"audio={audio_duration:.2f}s gen={elapsed:.1f}s"
        )
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_matrix(manifest: dict) -> None:
    by_key = {
        (sample["engine"], sample["gender"], sample["state"]): sample
        for sample in manifest["samples"]
    }
    engine_order = ["kokoro", "kokoro_onnx", "cosy", "edge"]
    gender_order = ["male", "female"]

    rows = []
    for engine in engine_order:
        for gender in gender_order:
            cells = []
            for state in STATES:
                sample = by_key.get((engine, gender, state))
                if sample:
                    cells.append(
                        f"""
          <td>
            <audio controls preload="metadata" title="{sample["file"]}" src="{sample["file"]}"></audio>
          </td>"""
                    )
                else:
                    cells.append('<td class="missing">missing</td>')
            rows.append(
                f"""
        <tr>
          <th>{ENGINE_LABELS[engine]}</th>
          <th>{GENDERS[gender]["label"]}</th>
          {''.join(cells)}
        </tr>"""
            )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TTS Engine Gender-State Matrix</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #202124; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    .meta {{ color: #5f6368; margin-bottom: 18px; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
    th, td {{ border: 1px solid #dadce0; padding: 10px; vertical-align: top; }}
    thead th {{ background: #f8f9fa; position: sticky; top: 0; z-index: 1; }}
    tbody th {{ width: 140px; background: #fbfbfc; }}
    audio {{ width: 100%; min-width: 180px; }}
    .line {{ color: #5f6368; font-size: 13px; font-weight: 400; margin-top: 4px; }}
    .missing {{ color: #b3261e; }}
  </style>
</head>
<body>
  <h1>TTS Engine Gender-State Matrix</h1>
  <div class="meta">Generated at {manifest["updated_at"]}. Rows are engine + gender; columns are dialogue states.</div>
  <table>
    <thead>
      <tr>
        <th>Engine</th>
        <th>Gender</th>
        {''.join(f'<th>{cfg["label"]}<div class="line">{cfg["text"]}</div></th>' for cfg in STATES.values())}
      </tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    MATRIX_PATH.write_text(html, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=["kokoro", "kokoro_onnx", "cosy", "edge"],
        default=["kokoro", "kokoro_onnx", "cosy", "edge"],
    )
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
    manifest = base_manifest()
    if "kokoro" in args.engines:
        generate_kokoro(manifest)
    if "kokoro_onnx" in args.engines:
        generate_kokoro_onnx(manifest)
    if "cosy" in args.engines:
        generate_cosy(manifest)
    if "edge" in args.engines:
        asyncio.run(generate_edge(manifest))

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_matrix(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
