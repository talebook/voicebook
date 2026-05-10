"""
CosyVoice2 TTS 引擎 - 支持情感语气控制

使用 CosyVoice2-0.5B 的 instruct2 模式，将角色画像中的情绪状态
自动转化为自然语言指令，实现"中年男性·着急""中年男性·激动"等
不同语气的高质量语音合成。

支持两种运行模式：
  - HTTP 模式：调用 CosyVoice2 FastAPI 服务（Docker 部署）
  - SDK 模式：直接加载本地模型（需安装 cosyvoice 包）
"""

import io
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 情感枚举 & 指令映射
# ---------------------------------------------------------------------------

class Emotion(str, Enum):
    """有声书常见情感类型"""
    ANXIOUS     = "着急"
    RELAXED     = "轻松"
    LOW_DEEP    = "低沉"
    EXCITED     = "激动"
    ANGRY       = "愤怒"
    SAD         = "悲伤"
    CALM        = "平静"
    TENDER      = "温柔"
    SOLEMN      = "威严"
    SARCASTIC   = "嘲讽"
    FEARFUL     = "恐惧"
    JOYFUL      = "喜悦"


# 情感 → CosyVoice instruct 指令文本
# 风格：指定语速、语调、力度等多个维度，效果更稳定
EMOTION_INSTRUCT_MAP: dict[str, str] = {
    Emotion.ANXIOUS:   "用急促紧张的语气，语速明显加快，略带焦虑感",
    Emotion.RELAXED:   "用轻松随意的语气，语调平缓自然，不紧不慢",
    Emotion.LOW_DEEP:  "用低沉沉稳的语气，语速缓慢，语调深沉有力",
    Emotion.EXCITED:   "用非常激动兴奋的语气，语速偏快，充满热情",
    Emotion.ANGRY:     "用愤怒强硬的语气，咬字有力，语速较快",
    Emotion.SAD:       "用悲伤沉重的语气，语速缓慢，情绪低落",
    Emotion.CALM:      "用平静淡然的语气，语速适中，不带任何波动",
    Emotion.TENDER:    "用温柔亲切的语气，语调柔和，如话家常",
    Emotion.SOLEMN:    "用威严庄重的语气，字正腔圆，语速沉稳有力",
    Emotion.SARCASTIC: "用略带嘲讽的语气，尾音稍稍上扬",
    Emotion.FEARFUL:   "用害怕颤抖的语气，声音有些不稳，语速忽快忽慢",
    Emotion.JOYFUL:    "用喜悦愉快的语气，语调明亮，充满笑意",
}

# 当 LLM 输出的 emotional_state 关键字 → Emotion 枚举
_KEYWORD_TO_EMOTION: list[tuple[list[str], Emotion]] = [
    # 优先级从高到低：越具体的情感放越前面
    (["愤怒", "生气", "暴怒", "怒火", "恼怒"],                 Emotion.ANGRY),
    (["恐惧", "害怕", "恐慌", "惊恐", "畏惧"],                 Emotion.FEARFUL),
    (["悲伤", "悲痛", "沮丧", "难过", "哀伤", "痛苦", "哀痛"],  Emotion.SAD),
    (["激动", "兴奋", "热情", "亢奋", "振奋", "豪情"],          Emotion.EXCITED),
    (["喜悦", "高兴", "快乐", "开心", "欣喜"],                 Emotion.JOYFUL),
    (["着急", "焦虑", "紧张", "急迫", "慌"],                   Emotion.ANXIOUS),
    (["嘲讽", "讥讽", "嘲笑", "讥笑", "戏谑"],                 Emotion.SARCASTIC),
    (["温柔", "温和", "亲切", "柔和"],                         Emotion.TENDER),
    (["威严", "庄重", "严肃", "肃穆"],                         Emotion.SOLEMN),
    (["低沉", "沉重", "压抑", "阴郁", "感慨", "沧桑", "深沉"],  Emotion.LOW_DEEP),
    (["轻松", "放松", "休闲", "悠闲", "随意"],                 Emotion.RELAXED),
    (["平静", "淡然", "冷静", "从容", "镇定"],                 Emotion.CALM),
]


def detect_emotion(emotional_state: str) -> Emotion:
    """从 LLM 输出的 emotional_state 字段中识别最匹配的情感枚举。"""
    for keywords, emotion in _KEYWORD_TO_EMOTION:
        if any(kw in emotional_state for kw in keywords):
            return emotion
    return Emotion.CALM


def build_instruct_text(
    emotion: Emotion,
    age_stage: str = "",
    extra_desc: str = "",
) -> str:
    """
    构建完整的 instruct_text。

    示例输出：
      "用低沉沉稳的语气，语速缓慢，语调深沉有力。声音略显苍老，带有岁月积淀的厚重感。"
    """
    base = EMOTION_INSTRUCT_MAP.get(emotion, EMOTION_INSTRUCT_MAP[Emotion.CALM])

    # 根据年龄阶段叠加音色描述
    age_hint = {
        "童年": "声音清脆稚嫩，像个孩子",
        "少年": "声音清亮，略带青涩",
        "青年": "声音清晰有力，充满活力",
        "中年": "声音浑厚沉稳，带有岁月感",
        "老年": "声音略显沙哑苍老，气息稍显不足",
    }.get(age_stage, "")

    parts = [base]
    if age_hint:
        parts.append(age_hint)
    if extra_desc:
        parts.append(extra_desc)

    return "。".join(parts)


# ---------------------------------------------------------------------------
# 音色选择：年龄阶段 → SFT speaker_id
# ---------------------------------------------------------------------------

# CosyVoice2-0.5B 内置 SFT 音色
VOICE_MAP: dict[str, dict[str, str]] = {
    # 格式: age_stage → {"male": spk_id, "female": spk_id}
    "童年":  {"male": "中文男", "female": "中文女"},
    "少年":  {"male": "中文男", "female": "中文女"},
    "青年":  {"male": "中文男", "female": "中文女"},
    "中年":  {"male": "中文男", "female": "中文女"},
    "老年":  {"male": "中文男", "female": "中文女"},
    "未知":  {"male": "中文男", "female": "中文女"},
}

def select_voice(age_stage: str, gender: str = "male") -> str:
    """根据年龄阶段和性别选择 SFT speaker_id。"""
    stage = age_stage if age_stage in VOICE_MAP else "未知"
    g = "male" if "男" in gender or gender == "male" else "female"
    return VOICE_MAP[stage][g]


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class SynthesisRequest:
    """单次 TTS 合成请求"""
    text: str
    spk_id: str              # SFT speaker id，如"中文男"
    instruct_text: str       # 情感指令
    speed: float = 1.0
    stream: bool = False


@dataclass
class SynthesisResult:
    """TTS 合成结果"""
    audio_bytes: bytes        # WAV 音频字节
    sample_rate: int
    duration_seconds: float
    request: SynthesisRequest
    latency_seconds: float


# ---------------------------------------------------------------------------
# HTTP 客户端（对接 CosyVoice2 FastAPI 服务）
# ---------------------------------------------------------------------------

class CosyVoice2HTTPClient:
    """
    调用运行在 Docker 中的 CosyVoice2 FastAPI 服务。

    服务端点（CosyVoice 官方 runtime/python/fastapi）：
      POST /api/inference/instruct2   - 情感指令合成
      POST /api/inference/sft         - 预设音色合成
      POST /api/inference/zero_shot   - 零样本克隆合成
      GET  /                          - 健康检查
    """

    def __init__(self, base_url: str = "http://localhost:50000"):
        self.base_url = base_url.rstrip("/")
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def health_check(self) -> bool:
        try:
            resp = self._get_session().get(f"{self.base_url}/", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def synthesize_instruct2(self, req: SynthesisRequest) -> bytes:
        """
        调用 instruct2 端点，返回原始 WAV bytes。
        服务端流式返回多个音频块，此处拼接为完整 WAV。
        """
        import requests as req_lib

        payload = {
            "tts_text":      req.text,
            "spk_id":        req.spk_id,
            "instruct_text": req.instruct_text,
            "stream":        False,
            "speed":         req.speed,
        }

        resp = self._get_session().post(
            f"{self.base_url}/api/inference/instruct2",
            json=payload,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()

        # 服务端返回 audio/wav 流，拼接所有 chunks
        buf = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                buf.write(chunk)
        return buf.getvalue()

    def synthesize_sft(self, text: str, spk_id: str, speed: float = 1.0) -> bytes:
        payload = {"tts_text": text, "spk_id": spk_id, "stream": False, "speed": speed}
        resp = self._get_session().post(
            f"{self.base_url}/api/inference/sft",
            json=payload,
            timeout=120,
            stream=True,
        )
        resp.raise_for_status()
        buf = io.BytesIO()
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                buf.write(chunk)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# SDK 客户端（直接加载本地 CosyVoice2 模型）
# ---------------------------------------------------------------------------

class CosyVoice2SDKClient:
    """
    直接调用本地 CosyVoice2 SDK（需安装 cosyvoice 包）。
    用于非 Docker 环境或开发调试。
    """

    def __init__(self, model_dir: str = "pretrained_models/CosyVoice2-0.5B"):
        self.model_dir = model_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from cosyvoice.cli.cosyvoice import CosyVoice2
            logger.info("加载 CosyVoice2 模型: %s", self.model_dir)
            self._model = CosyVoice2(self.model_dir, load_jit=True, load_trt=False)
            logger.info("CosyVoice2 模型加载完成，采样率: %d", self._model.sample_rate)
        return self._model

    @property
    def sample_rate(self) -> int:
        return self._load().sample_rate

    def synthesize_instruct2(self, req: SynthesisRequest) -> tuple[bytes, int]:
        """返回 (wav_bytes, sample_rate)"""
        import torchaudio

        model = self._load()
        audio_parts = []
        for chunk in model.inference_instruct2(
            req.text,
            req.spk_id,
            instruct_text=req.instruct_text,
            stream=req.stream,
            speed=req.speed,
        ):
            audio_parts.append(chunk["tts_speech"])

        import torch
        audio = torch.cat(audio_parts, dim=-1)

        buf = io.BytesIO()
        torchaudio.save(buf, audio, model.sample_rate, format="wav")
        return buf.getvalue(), model.sample_rate

    def synthesize_sft(
        self, text: str, spk_id: str, speed: float = 1.0
    ) -> tuple[bytes, int]:
        import torchaudio, torch

        model = self._load()
        parts = []
        for chunk in model.inference_sft(text, spk_id, stream=False, speed=speed):
            parts.append(chunk["tts_speech"])
        audio = torch.cat(parts, dim=-1)
        buf = io.BytesIO()
        torchaudio.save(buf, audio, model.sample_rate, format="wav")
        return buf.getvalue(), model.sample_rate


# ---------------------------------------------------------------------------
# 主引擎：统一接口
# ---------------------------------------------------------------------------

class CosyVoice2TTS:
    """
    CosyVoice2 TTS 引擎 - 对外统一接口。

    自动选择后端：
      1. 优先尝试 HTTP 服务（Docker）
      2. 回退到本地 SDK
      3. 都不可用时抛出 RuntimeError

    快速开始：
        tts = CosyVoice2TTS()

        # 方式一：直接指定情感枚举
        result = tts.synthesize("这件事我不能接受！", emotion=Emotion.ANGRY)

        # 方式二：传入角色画像（自动推断情感）
        result = tts.synthesize_for_character(
            text="你快点！时间来不及了！",
            age_stage="中年",
            gender="男",
            emotional_state="着急",
        )
        with open("output.wav", "wb") as f:
            f.write(result.audio_bytes)
    """

    def __init__(
        self,
        http_url: str = "http://localhost:50000",
        sdk_model_dir: str = "pretrained_models/CosyVoice2-0.5B",
        prefer_http: bool = True,
    ):
        self._http_url = http_url
        self._sdk_model_dir = sdk_model_dir
        self._prefer_http = prefer_http
        self._http_client: Optional[CosyVoice2HTTPClient] = None
        self._sdk_client: Optional[CosyVoice2SDKClient] = None
        self._backend: Optional[str] = None  # "http" | "sdk"

    # ------------------------------------------------------------------
    # 后端初始化
    # ------------------------------------------------------------------

    def _init_backend(self):
        if self._backend is not None:
            return

        if self._prefer_http:
            client = CosyVoice2HTTPClient(self._http_url)
            if client.health_check():
                self._http_client = client
                self._backend = "http"
                logger.info("CosyVoice2 后端: HTTP (%s)", self._http_url)
                return

        try:
            client = CosyVoice2SDKClient(self._sdk_model_dir)
            _ = client.sample_rate  # 触发模型加载
            self._sdk_client = client
            self._backend = "sdk"
            logger.info("CosyVoice2 后端: 本地 SDK (%s)", self._sdk_model_dir)
        except Exception as e:
            raise RuntimeError(
                "CosyVoice2 后端不可用。\n"
                f"  HTTP ({self._http_url}): 服务未响应\n"
                f"  SDK ({self._sdk_model_dir}): {e}\n"
                "请启动 CosyVoice2 Docker 服务或安装 cosyvoice 包。"
            ) from e

    # ------------------------------------------------------------------
    # 核心合成接口
    # ------------------------------------------------------------------

    def synthesize(
        self,
        text: str,
        emotion: Emotion = Emotion.CALM,
        spk_id: str = "中文男",
        age_stage: str = "中年",
        speed: float = 1.0,
        extra_instruct: str = "",
    ) -> SynthesisResult:
        """
        合成带情感的语音。

        Args:
            text:          待合成文本
            emotion:       情感枚举
            spk_id:        SFT speaker id（默认"中文男"）
            age_stage:     年龄阶段（影响 instruct 中的音色描述）
            speed:         语速（0.5~2.0，默认 1.0）
            extra_instruct: 附加 instruct 描述（可为空）
        """
        self._init_backend()

        instruct_text = build_instruct_text(emotion, age_stage, extra_instruct)
        req = SynthesisRequest(
            text=text,
            spk_id=spk_id,
            instruct_text=instruct_text,
            speed=speed,
        )

        t0 = time.time()
        if self._backend == "http":
            audio_bytes = self._http_client.synthesize_instruct2(req)
            sample_rate = 22050  # CosyVoice2 默认采样率
        else:
            audio_bytes, sample_rate = self._sdk_client.synthesize_instruct2(req)

        latency = time.time() - t0
        duration = _estimate_duration(audio_bytes, sample_rate)

        logger.info(
            "[TTS] %s | 情感=%s | spk=%s | 耗时=%.2fs | 时长=%.1fs",
            text[:20], emotion.value, spk_id, latency, duration,
        )

        return SynthesisResult(
            audio_bytes=audio_bytes,
            sample_rate=sample_rate,
            duration_seconds=duration,
            request=req,
            latency_seconds=latency,
        )

    def synthesize_for_character(
        self,
        text: str,
        age_stage: str = "中年",
        gender: str = "男",
        emotional_state: str = "平静",
        temperament: str = "",
        speed: float = 1.0,
    ) -> SynthesisResult:
        """
        根据角色画像（LLM 分析结果）自动推断情感并合成语音。

        直接传入 CharacterProfile 的字段即可，无需手动指定情感枚举。

        Args:
            text:            待合成文本
            age_stage:       年龄阶段（童年/少年/青年/中年/老年）
            gender:          性别（男/女）
            emotional_state: LLM 输出的情绪状态描述
            temperament:     气质性格（作为附加 instruct 参考）
            speed:           语速
        """
        emotion = detect_emotion(emotional_state)
        spk_id = select_voice(age_stage, gender)
        return self.synthesize(
            text=text,
            emotion=emotion,
            spk_id=spk_id,
            age_stage=age_stage,
            speed=speed,
            extra_instruct=temperament[:20] if temperament else "",
        )

    def list_voices(self) -> list[str]:
        """列出所有可用 SFT 音色 ID。"""
        self._init_backend()
        if self._backend == "sdk":
            return self._sdk_client._load().list_available_spks()
        # HTTP 模式暂不支持动态查询，返回已知列表
        return ["中文男", "中文女", "英文男", "英文女", "日语男", "粤语女"]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _estimate_duration(wav_bytes: bytes, sample_rate: int) -> float:
    """从 WAV 字节估算音频时长（秒）。"""
    # WAV header = 44 bytes，16-bit PCM
    if len(wav_bytes) <= 44:
        return 0.0
    pcm_bytes = len(wav_bytes) - 44
    num_samples = pcm_bytes // 2  # 16-bit = 2 bytes/sample
    return num_samples / max(sample_rate, 1)


def save_wav(result: SynthesisResult, path: str):
    """将合成结果保存为 WAV 文件。"""
    with open(path, "wb") as f:
        f.write(result.audio_bytes)
    logger.info("音频已保存: %s (%.1fs)", path, result.duration_seconds)


def batch_synthesize(
    tts: CosyVoice2TTS,
    items: list[dict],
    output_dir: str = "output_audio",
) -> list[SynthesisResult]:
    """
    批量合成。items 格式：
        [{"text": "...", "emotion": Emotion.EXCITED, "filename": "01.wav"}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for i, item in enumerate(items):
        emotion = item.get("emotion", Emotion.CALM)
        if isinstance(emotion, str):
            emotion = Emotion(emotion)
        result = tts.synthesize(
            text=item["text"],
            emotion=emotion,
            spk_id=item.get("spk_id", "中文男"),
            age_stage=item.get("age_stage", "中年"),
            speed=item.get("speed", 1.0),
        )
        filename = item.get("filename", f"{i+1:03d}.wav")
        save_wav(result, os.path.join(output_dir, filename))
        results.append(result)
    return results
