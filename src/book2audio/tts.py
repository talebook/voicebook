"""TTS 引擎抽象：统一 (text, VoiceSpec) -> 音频文件接口。

引擎：
  edge      EdgeEngine（云，免费，快，基线）
  qwen      Qwen3TTSAIEngine（qwen3ttsai.com 公共 Web API）

CosyVoice3 相关代码仅作历史实验保留，不再接入主流程。后续新增本地模型时，
单模型磁盘体积目标约 500MB。
"""

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VoiceSpec:
    """引擎无关的音色描述；Qwen 只使用 ``voice`` 字段。"""
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


class QwenTTSAPIError(RuntimeError):
    """qwen3ttsai.com 返回了不能用于合成的响应。"""


class QwenTTSClient:
    """qwen3ttsai.com 无登录 TTS HTTP 客户端。

    该协议来自站点前端 bundle，并用真实请求验证：POST JSON
    ``{text, voice, mode}``，成功时返回 24 kHz mono PCM WAV。
    """

    DEFAULT_BASE_URL = "https://qwen3ttsai.com"
    MAX_TEXT_CHARS = 1000

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_attempts: int = 3,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.base_url = (base_url or os.getenv("QWEN3TTS_BASE_URL") or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.session.headers.update({
            "Accept": "audio/wav,*/*",
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/zh",
            "User-Agent": "voicebook/0.1 (+https://qwen3ttsai.com)",
        })

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/api/qwen3tts/generate"

    def close(self) -> None:
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def generate(self, text: str, voice: str, mode: str = "system") -> bytes:
        """合成一个不超过站点 1000 字限制的 WAV。"""
        if not text.strip():
            raise ValueError("TTS 文本不能为空")
        if len(text) > self.MAX_TEXT_CHARS:
            raise ValueError(f"Qwen 单次文本不能超过 {self.MAX_TEXT_CHARS} 字")
        if not voice.strip():
            raise ValueError("Qwen 音色不能为空")

        payload = {"text": text, "voice": voice, "mode": mode}
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(self.max_attempts):
            attempts = attempt + 1
            try:
                response = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 == self.max_attempts:
                    break
                self.sleeper(2 ** attempt)
                continue

            if response.status_code == 200:
                content_type = response.headers.get("content-type", "").lower()
                audio = response.content
                if "audio/wav" not in content_type:
                    preview = response.text[:200] if hasattr(response, "text") else ""
                    raise QwenTTSAPIError(f"Qwen 返回格式异常: {content_type or 'unknown'} {preview}")
                if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
                    raise QwenTTSAPIError("Qwen 返回了无效 WAV 数据")
                return audio

            preview = response.text[:200] if hasattr(response, "text") else ""
            last_error = QwenTTSAPIError(f"Qwen HTTP {response.status_code}: {preview}")
            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if not retryable or attempt + 1 == self.max_attempts:
                break
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            self.sleeper(min(max(delay, 0.0), 30.0))

        raise QwenTTSAPIError(f"Qwen 合成失败（已尝试 {attempts} 次）") from last_error

    def synth_to_file(self, text: str, voice: str, out_path: Path) -> Path:
        audio = self.generate(text, voice)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
        return out_path


def split_tts_text(text: str, max_chars: int = QwenTTSClient.MAX_TEXT_CHARS) -> list[str]:
    """按句末标点切开长文本，保证每个请求不超过 API 上限。"""
    if max_chars < 1:
        raise ValueError("max_chars 必须大于 0")
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        window = remaining[:max_chars]
        cut = max((window.rfind(mark) + 1 for mark in "。！？!?；;，,\n"), default=0)
        if cut < max_chars // 2:
            cut = max_chars
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].strip()
    return chunks


class Qwen3TTSAIEngine:
    """异步适配器；每个并发请求使用独立 Session，避免跨线程共享状态。"""

    name = "qwen"
    CONCURRENCY = 2

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url
        self._sem = asyncio.Semaphore(self.CONCURRENCY)

    async def synth(self, text: str, spec: VoiceSpec, out_path: Path):
        async with self._sem:
            def generate():
                with QwenTTSClient(base_url=self.base_url) as client:
                    return client.synth_to_file(text, spec.voice, out_path)

            await asyncio.to_thread(generate)


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
    if name == "qwen":
        return Qwen3TTSAIEngine()
    raise SystemExit(f"未知或已停用的 TTS 引擎: {name}（当前支持 edge、qwen）")
