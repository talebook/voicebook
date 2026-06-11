"""TTS 引擎抽象：统一 (text, VoiceSpec) -> 音频文件 接口

引擎：
  edge      EdgeEngine（云，免费，快，基线）
  cosyvoice CosyVoiceEngine（本地，真人感更强；通过子进程调用 temp_cosyvoice 隔离环境，
            依赖与主环境冲突大，因此不做进程内 import）
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VoiceSpec:
    """引擎无关的音色描述。edge 用 voice/rate/pitch；cosyvoice 用 spk 预置音色名。"""
    voice: str          # edge: zh-CN-XxxNeural; cosyvoice: 预置说话人/参考音频名
    rate: str = "+0%"
    pitch: str = "+0Hz"


class EdgeEngine:
    name = "edge"
    CONCURRENCY = 4
    MAX_RETRIES = 3

    def __init__(self):
        self._sem = asyncio.Semaphore(self.CONCURRENCY)

    async def synth(self, text: str, spec: VoiceSpec, out_path: Path):
        import edge_tts
        async with self._sem:
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    await edge_tts.Communicate(text, spec.voice, rate=spec.rate,
                                               pitch=spec.pitch).save(str(out_path))
                    if out_path.stat().st_size > 0:
                        return
                except Exception as e:
                    if attempt == self.MAX_RETRIES:
                        raise RuntimeError(f"edge-tts failed: {text[:30]}...") from e
                    await asyncio.sleep(2 * attempt)


class CosyVoiceEngine:
    """以批处理子进程方式调用 CosyVoice（独立venv），一次进程处理一批文本均摊模型加载。"""
    name = "cosyvoice"
    REPO = ROOT / "temp_cosyvoice"
    MODEL = ROOT / "pretrained_models/Fun-CosyVoice3-0.5B"

    def __init__(self):
        self._batch = []   # [(text, spec, out_path)]

    async def synth(self, text: str, spec: VoiceSpec, out_path: Path):
        self._batch.append({"text": text, "voice": spec.voice, "out": str(out_path)})

    def flush(self):
        """执行积累的合成任务（子进程内一次性加载模型）。"""
        if not self._batch:
            return
        job_file = self.MODEL.parent / "_cosy_jobs.json"
        job_file.write_text(json.dumps(self._batch, ensure_ascii=False))
        worker = Path(__file__).parent / "cosy_worker.py"
        subprocess.run(
            [str(self.REPO / ".venv/bin/python"), str(worker),
             "--model", str(self.MODEL), "--repo", str(self.REPO), "--jobs", str(job_file)],
            check=True,
        )
        self._batch.clear()
        job_file.unlink(missing_ok=True)


def get_engine(name: str):
    if name == "edge":
        return EdgeEngine()
    if name == "cosyvoice":
        return CosyVoiceEngine()
    raise SystemExit(f"未知 TTS 引擎: {name}（可选 edge / cosyvoice）")
