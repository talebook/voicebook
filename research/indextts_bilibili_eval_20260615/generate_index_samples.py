#!/usr/bin/env python3
"""Generate the Voicebook emotion-state samples with Bilibili IndexTTS2.

This wrapper assumes the official index-tts repository and checkpoints have
already been installed. It intentionally keeps those large files outside this
Voicebook repository.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = EVAL_DIR / "samples"
MANIFEST_PATH = EVAL_DIR / "manifest.json"

STATES = {
    "weak": {
        "label": "虚弱",
        "text": "我没事……别停下，先把药箱拿过来。",
        "kwargs": {
            "emo_vector": [0, 0, 0.55, 0.15, 0, 0.45, 0, 0.1],
            "emo_alpha": 0.7,
            "use_random": False,
        },
    },
    "angry": {
        "label": "愤怒",
        "text": "够了！你还想瞒我到什么时候？",
        "kwargs": {
            "emo_vector": [0, 0.9, 0, 0, 0.15, 0, 0.1, 0],
            "emo_alpha": 0.8,
            "use_random": False,
        },
    },
    "whisper": {
        "label": "低语",
        "text": "别出声……门外有人。",
        "kwargs": {
            "emo_text": "压低声音，小声耳语，紧张但克制。",
            "emo_alpha": 0.55,
            "use_emo_text": True,
            "use_random": False,
        },
    },
}


def require_path(env_name: str) -> Path:
    value = os.environ.get(env_name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {env_name}")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"{env_name} does not exist: {path}")
    return path


def main() -> int:
    repo = require_path("INDEXTTS_REPO")
    checkpoints = require_path("INDEXTTS_CHECKPOINTS")
    spk_prompt = require_path("INDEXTTS_SPK_PROMPT")

    sys.path.insert(0, str(repo))
    from indextts.infer_v2 import IndexTTS2

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    tts = IndexTTS2(
        cfg_path=str(checkpoints / "config.yaml"),
        model_dir=str(checkpoints),
        use_fp16=False,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )

    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "engine": "IndexTTS2",
        "repo": str(repo),
        "checkpoints": str(checkpoints),
        "speaker_prompt": str(spk_prompt),
        "samples": [],
    }

    for state, cfg in STATES.items():
        out = SAMPLE_DIR / f"{state}_indextts2.wav"
        t0 = time.time()
        tts.infer(
            spk_audio_prompt=str(spk_prompt),
            text=cfg["text"],
            output_path=str(out),
            verbose=True,
            **cfg["kwargs"],
        )
        manifest["samples"].append(
            {
                "state": state,
                "state_label": cfg["label"],
                "text": cfg["text"],
                "file": str(out.relative_to(EVAL_DIR)),
                "controls": cfg["kwargs"],
                "seconds_to_generate": round(time.time() - t0, 2),
                "bytes": out.stat().st_size,
            }
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
