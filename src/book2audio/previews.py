"""音色目录与十场景预生成试听资产发现。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .voice_casting import CATALOGS


PREVIEW_SCENES = (
    ("narration", "旁白", "夜色渐深，远处的灯火一盏接一盏亮了起来。"),
    ("daily", "日常", "你先坐一会儿，我把手里的事情忙完就来。"),
    ("joy", "喜悦", "太好了，我们终于赶在天黑之前到了！"),
    ("anger", "愤怒", "够了，这件事绝不能再这样拖下去！"),
    ("sadness", "悲伤", "她低下头，很久以后才轻声说，我明白了。"),
    ("fear", "恐惧", "别出声，门外好像有什么东西正在靠近。"),
    ("whisper", "低语", "听我说，等钟声响起，我们就从后门离开。"),
    ("urgent", "急切", "快一点，桥马上就要断了，所有人立刻撤离！"),
    ("authority", "威严", "从现在起，任何人不得擅自离开自己的位置。"),
    ("tenderness", "温柔", "别担心，我会一直在这里陪着你。"),
)


def assets_root() -> Path:
    return Path(__file__).parent / "assets" / "voice-previews"


def preview_catalog(engine: str | None = None, *, include_paths: bool = False) -> dict:
    packaged = assets_root() / "catalog.json"
    generated = {}
    if packaged.is_file():
        payload = json.loads(packaged.read_text(encoding="utf-8"))
        generated = {
            (item["engine"], item["voice_id"]): item
            for item in payload.get("voices", [])
        }
    engines = [engine] if engine else sorted(CATALOGS)
    voices = []
    for engine_name in engines:
        if engine_name not in CATALOGS:
            raise ValueError(f"未知 TTS 引擎：{engine_name}")
        for profile in CATALOGS[engine_name]:
            preview = generated.get((engine_name, profile.voice_id), {})
            relative = preview.get("audio", "")
            audio = assets_root() / relative if relative else None
            item = {
                "engine": engine_name,
                **asdict(profile),
                "preview_available": bool(audio and audio.is_file()),
                "preview_scenes": preview.get("scenes", []),
            }
            if include_paths and audio and audio.is_file():
                item["preview_path"] = str(audio.resolve())
            voices.append(item)
    return {
        "format": "voicebook-voice-catalog",
        "version": 1,
        "scene_definitions": [
            {"id": scene_id, "name": name, "text": text}
            for scene_id, name, text in PREVIEW_SCENES
        ],
        "voices": voices,
    }
