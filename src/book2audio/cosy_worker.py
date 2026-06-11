"""CosyVoice3 批量合成 worker——运行在 temp_cosyvoice/.venv 隔离环境中

用法（由 CosyVoiceEngine 子进程调用）:
  .venv/bin/python cosy_worker.py --model <模型目录> --repo <CosyVoice仓库> --jobs <jobs.json>

CosyVoice3 为 zero-shot 克隆：每个音色 = 参考音频 + 其转写文本。
jobs.json: [{"text": "...", "prompt_wav": "ref.wav", "prompt_text": "参考音频转写", "out": "out.wav"}]
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--jobs", required=True)
    args = ap.parse_args()

    sys.path.insert(0, args.repo)
    sys.path.insert(0, str(Path(args.repo) / "third_party/Matcha-TTS"))
    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    t0 = time.time()
    cosyvoice = AutoModel(model_dir=args.model)
    print(f"[cosy_worker] 模型加载 {time.time() - t0:.1f}s")

    jobs = json.loads(Path(args.jobs).read_text())
    for i, job in enumerate(jobs):
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        wavs = [r["tts_speech"] for r in cosyvoice.inference_zero_shot(
            job["text"], PROMPT_PREFIX + job["prompt_text"], job["prompt_wav"], stream=False)]
        torchaudio.save(str(out), torch.cat(wavs, dim=1), cosyvoice.sample_rate)
        dur = sum(w.shape[1] for w in wavs) / cosyvoice.sample_rate
        print(f"[cosy_worker] {i + 1}/{len(jobs)} {out.name} 音频{dur:.1f}s 合成{time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
