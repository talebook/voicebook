# book2audio 架构研究

## 1. 系统架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        book2audio                                │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   CLI/Web   │ → │   FastAPI   │ → │  Processing │        │
│  │   Interface │   │   Server    │   │   Pipeline  │        │
│  └──────────────┘   └──────────────┘   └──────────────┘        │
│                                              │                   │
│                                              ▼                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │  Audio Files │ ← │  Audio       │ ← │    TTS      │        │
│  │   Output     │   │  Assembly    │   │   Engine    │        │
│  └──────────────┘   └──────────────┘   └──────────────┘        │
│                                              ▲                   │
│                                              │                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │   TXT File   │ → │  Text       │ → │     LLM     │        │
│  │   Input     │   │  Analysis   │   │   (Qwen3)   │        │
│  └──────────────┘   └──────────────┘   └──────────────┘        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件

| 组件 | 职责 | 技术选型 |
|------|------|---------|
| **InputParser** | TXT解析、章节分割 | Python 正则 + NLP |
| **CharacterAnalyzer** | 角色识别、画像提取 | Qwen3-0.6B (Ollama) |
| **DialogueExtractor** | 对话/旁白分离 | 规则 + LLM |
| **VoiceSelector** | 音色选择与映射 | 规则引擎 |
| **TTSEngine** | 语音合成 | CosyVoice / Edge TTS |
| **AudioAssembler** | 音频拼接输出 | pydub |

---

## 2. 数据流

### 2.1 文本处理流程

```
novel.txt
    │
    ▼
┌─────────────────┐
│ 1. InputParser  │ ───→ chapters: List[Chapter]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. ChapterSplit │ ───→ 按章节标题分割
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. DialogueExtract│ ───→ dialogues + narration
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. CharacterID  │ ───→ character_map
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. ProfileExtract│ ───→ character_profiles
└─────────────────┘
```

### 2.2 音频生成流程

```
character_profiles + dialogues
        │
        ▼
┌─────────────────┐
│ 6. VoiceSelect  │ ───→ voice_mapping
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 7. TTSGenerate  │ ───→ audio_segments
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 8. AudioAssemble│ ───→ final_audio
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 9. Output       │ ───→ MP3/M4A
└─────────────────┘
```

---

## 3. 核心数据模型

### 3.1 章节数据

```python
@dataclass
class Chapter:
    number: int
    title: str
    content: str
    paragraphs: List[Paragraph]

@dataclass
class Paragraph:
    index: int
    type: str  # "dialogue" | "narration" | "description"
    speaker: Optional[str]  # 对话时说话者
    content: str
```

### 3.2 角色数据

```python
@dataclass
class Character:
    name: str
    gender: str
    age_stages: Dict[int, AgeStage]  # 章节号 → 年龄阶段

@dataclass
class AgeStage:
    chapter: int
    age_years: int
    age_label: str  # childhood/teen/young/middle/elderly
    voice_type: str
    temperament: str
    appearance: str
```

### 3.3 音频数据

```python
@dataclass
class AudioSegment:
    chapter: int
    speaker: str
    text: str
    voice: str
    audio_path: str
    start_time: float
    end_time: float

@dataclass
class ChapterAudio:
    chapter: int
    segments: List[AudioSegment]
    total_duration: float
    output_path: str
```

---

## 4. API 设计

### 4.1 REST API

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /api/analyze` | POST | 分析章节角色 |
| `POST /api/convert` | POST | 转换TXT到音频 |
| `POST /api/tts` | POST | 单独TTS合成 |
| `GET /api/character/{name}/arc` | GET | 角色发展轨迹 |
| `GET /api/voices` | GET | 可用音色列表 |
| `GET /api/progress/{job_id}` | GET | 任务进度 |
| `GET /api/health` | GET | 健康检查 |

### 4.2 请求示例

```json
// POST /api/convert
{
    "file_path": "/path/to/novel.txt",
    "chapters": [1, 2, 3],  // 可选
    "voice_mapping": {
        "张三": "female_young",
        "李四": "male_middle"
    },
    "output_format": "mp3",
    "output_dir": "/output"
}

// 响应
{
    "job_id": "uuid",
    "status": "processing",
    "progress": 0.25,
    "message": "分析第2章节..."
}
```

---

## 5. 构建顺序建议

### Phase 1: 文本处理
1. TXT 解析模块
2. 章节分割
3. 对话提取

### Phase 2: LLM 集成
1. Ollama 集成
2. 角色识别
3. 画像提取

### Phase 3: TTS 集成
1. CosyVoice/Edge TTS 集成
2. 音色映射
3. 年龄变化处理

### Phase 4: 音频处理
1. 音频拼接
2. 格式转换
3. 输出优化

---

*研究完成时间: 2026-05-09*
