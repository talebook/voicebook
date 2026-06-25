"""TTS 引擎抽象：统一 (text, VoiceSpec) -> 音频文件 接口

引擎：
  edge      EdgeEngine（云，免费，快，基线）

CosyVoice3 相关代码仅作历史实验保留，不再接入主流程。后续新增本地模型时，
单模型磁盘体积目标约 500MB。
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VoiceSpec:
    """引擎无关的音色描述。当前主流程使用 edge 的 voice/rate/pitch。"""
    voice: str          # edge: zh-CN-XxxNeural
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
    raise SystemExit(f"未知或已停用的 TTS 引擎: {name}（当前仅支持 edge）")
