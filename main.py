"""
小说角色文本画像识别系统
基于 Qwen3-0.6B 模型
"""
import json
import requests
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="小说角色画像识别API", version="1.0.0")

OLLAMA_BASE_URL = "http://ollama:11434"
MODEL_NAME = "qwen3:0.6b"

CHARACTER_PROMPT_TEMPLATE = """分析以下小说章节中角色「{character_name}」的状态。

【章节内容】
{chapter_content}

【分析要求】
请从以下维度分析该角色在当前章节的状态，用JSON格式输出：
- age_stage: 年龄阶段（童年/少年/青年/中年/老年）
- appearance: 外貌特征描述
- temperament: 气质/性格特征
- voice_description: 音色描述（用于TTS语音合成）
- emotional_state: 当前情绪状态
- key_changes: 与之前相比的重要变化

直接输出JSON，不要有其他内容。"""

@dataclass
class CharacterProfile:
    name: str
    chapter: int
    age_stage: str = "未知"
    appearance: str = ""
    temperament: str = ""
    voice_description: str = ""
    emotional_state: str = ""
    key_changes: str = ""
    confidence: float = 0.0
    timestamp: str = ""

@dataclass
class CharacterHistory:
    name: str
    profiles: Dict[int, CharacterProfile] = field(default_factory=dict)

    def add_profile(self, profile: CharacterProfile):
        self.profiles[profile.chapter] = profile

    def get_profile(self, chapter: int) -> Optional[CharacterProfile]:
        if chapter in self.profiles:
            return self.profiles[chapter]
        chapters = sorted(self.profiles.keys())
        for ch in reversed(chapters):
            if ch < chapter:
                return self.profiles[ch]
        return None

    def get_latest_profile(self) -> Optional[CharacterProfile]:
        if not self.profiles:
            return None
        return self.profiles[max(self.profiles.keys())]

class NovelCharacterProfiler:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = MODEL_NAME):
        self.base_url = base_url
        self.model = model
        self.character_history: Dict[str, CharacterHistory] = {}

    def call_llm(self, prompt: str, timeout: int = 120) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 512,
                        "stop": ["```", "```json"]
                    }
                },
                timeout=timeout
            )
            if response.status_code == 200:
                return response.json().get("response", "")
            else:
                return f"Error: {response.status_code}"
        except requests.exceptions.Timeout:
            return "Error: Timeout"
        except Exception as e:
            return f"Error: {str(e)}"

    def analyze_chapter(
        self,
        chapter_num: int,
        chapter_content: str,
        characters: List[str]
    ) -> Dict[str, CharacterProfile]:
        results = {}

        for char_name in characters:
            char_name = char_name.strip()
            if not char_name:
                continue

            previous_profile = None
            if char_name in self.character_history:
                previous_profile = self.character_history[char_name].get_latest_profile()

            profile = self._analyze_character(
                chapter_num, chapter_content, char_name, previous_profile
            )
            results[char_name] = profile

            if char_name not in self.character_history:
                self.character_history[char_name] = CharacterHistory(name=char_name)
            self.character_history[char_name].add_profile(profile)

        return results

    def _analyze_character(
        self,
        chapter_num: int,
        content: str,
        char_name: str,
        previous_profile: Optional[CharacterProfile] = None
    ) -> CharacterProfile:
        prompt = CHARACTER_PROMPT_TEMPLATE.format(
            character_name=char_name,
            chapter_content=content[:4000]
        )

        if previous_profile:
            prompt += f"\n\n【角色过往状态（参考）】\n"
            prompt += f"- 年龄阶段：{previous_profile.age_stage}\n"
            prompt += f"- 气质：{previous_profile.temperament}\n"
            prompt += f"- 音色：{previous_profile.voice_description}\n"

        response = self.call_llm(prompt)
        profile = self._parse_response(char_name, chapter_num, response)

        return profile

    def _parse_response(
        self,
        char_name: str,
        chapter_num: int,
        raw_response: str
    ) -> CharacterProfile:
        profile = CharacterProfile(
            name=char_name,
            chapter=chapter_num,
            timestamp=datetime.now().isoformat()
        )

        try:
            json_str = raw_response.strip()

            if "```json" in json_str:
                json_str = json_str.split("```json")[-1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[-1].split("```")[0]

            for remove_str in ["```", "json"]:
                json_str = json_str.replace(remove_str, "")

            json_str = json_str.strip()
            data = json.loads(json_str)

            profile.age_stage = data.get("age_stage", "未知")
            profile.appearance = data.get("appearance", "")
            profile.temperament = data.get("temperament", "")
            profile.voice_description = data.get("voice_description", "")
            profile.emotional_state = data.get("emotional_state", "")
            profile.key_changes = data.get("key_changes", "")
            profile.confidence = 0.8

        except json.JSONDecodeError as e:
            profile.temperament = raw_response[:200]
            profile.key_changes = f"JSON解析失败: {str(e)}"

        return profile

    def get_character_arc(self, char_name: str) -> Dict:
        if char_name not in self.character_history:
            return {}
        history = self.character_history[char_name]
        return {
            "character": char_name,
            "total_chapters": len(history.profiles),
            "age_progression": [
                {"chapter": p.chapter, "age_stage": p.age_stage}
                for p in sorted(history.profiles.values(), key=lambda x: x.chapter)
            ],
            "profiles": {
                ch: asdict(p) for ch, p in sorted(history.profiles.items())
            }
        }

profiler = NovelCharacterProfiler()

class ChapterAnalyzeRequest(BaseModel):
    chapter_num: int
    chapter_content: str
    characters: List[str]

class ChapterAnalyzeResponse(BaseModel):
    success: bool
    chapter: int
    results: Dict[str, dict]
    elapsed_time: float

@app.post("/analyze", response_model=ChapterAnalyzeResponse)
async def analyze_chapter(request: ChapterAnalyzeRequest):
    start_time = time.time()

    results = profiler.analyze_chapter(
        request.chapter_num,
        request.chapter_content,
        request.characters
    )

    elapsed = time.time() - start_time

    return ChapterAnalyzeResponse(
        success=True,
        chapter=request.chapter_num,
        results={name: asdict(profile) for name, profile in results.items()},
        elapsed_time=elapsed
    )

@app.get("/character/{char_name}/arc")
async def get_character_arc(char_name: str):
    arc = profiler.get_character_arc(char_name)
    if not arc:
        raise HTTPException(status_code=404, detail="Character not found")
    return arc

@app.get("/health")
async def health_check():
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/", timeout=5)
        return {
            "status": "healthy" if response.status_code == 200 else "unhealthy",
            "model": MODEL_NAME
        }
    except:
        return {"status": "ollama_not_running", "model": MODEL_NAME}

@app.get("/")
async def root():
    return {
        "service": "小说角色画像识别系统",
        "model": MODEL_NAME,
        "endpoints": {
            "POST /analyze": "分析章节角色画像",
            "GET /character/{name}/arc": "获取角色发展轨迹",
            "GET /health": "健康检查"
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
