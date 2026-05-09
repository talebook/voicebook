# book2audio 技术栈文档

## 1. 技术栈概览

| 层级 | 技术选型 | 版本/规格 |
|------|---------|----------|
| **运行时** | Python | 3.10+ |
| **LLM** | Qwen3-0.6B (Ollama) | 0.6B参数，~600MB内存 |
| **TTS** | kokoro-onnx / Edge TTS | 本地部署/云API |
| **Web框架** | FastAPI | 扩展现有服务 |
| **容器化** | Docker + Docker Compose | 完整部署方案 |
| **音频处理** | pydub, soundfile | 音频拼接与转换 |

---

## 2. LLM 技术栈

### 2.1 模型选型

**首选**: Qwen3-0.6B

| 规格 | 值 |
|------|-----|
| 参数量 | 0.6B (6亿) |
| 模型大小 | ~523MB (FP16) |
| 量化后内存 | ~600MB (Q4) |
| 上下文窗口 | 40K tokens |
| 中文能力 | ⭐⭐⭐⭐⭐ |
| Ollama 模型名 | `qwen3:0.6b` |

**备选**: Qwen2.5-0.5B

| 规格 | 值 |
|------|-----|
| 参数量 | 0.5B |
| 量化后内存 | ~500MB |
| Ollama 模型名 | `qwen2.5:0.5b` |

### 2.2 Ollama 部署

```bash
# 安装 Ollama (macOS/Linux)
curl -fsSL https://ollama.com/install.sh | sh

# 拉取模型
ollama pull qwen3:0.6b

# 运行
ollama serve  # 启动服务，端口 11434
```

### 2.3 API 调用

```python
import requests

def call_llm(prompt: str, base_url: str = "http://localhost:11434"):
    response = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": "qwen3:0.6b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 512
            }
        }
    )
    return response.json()["response"]
```

---

## 3. TTS 技术栈

### 3.1 推荐方案

**首选**: kokoro-onnx (轻量级本地TTS)

| 特性 | 值 |
|------|-----|
| 模型大小 | ~310MB |
| 量化后 | ~80MB |
| 多语言支持 | 54+音色 |
| 内存需求 | 低 |
| 部署 | 完全本地 |
| GitHub | thewh1teagle/kokoro-onnx |

**快速原型**: Edge TTS (微软)

| 特性 | 值 |
|------|-----|
| 中文音色 | 10+ |
| 部署 | 云API（免费） |
| 网络要求 | 需要 |
| 优势 | 无需本地部署 |

**备选**: CosyVoice (需要Docker)

| 特性 | 值 |
|------|-----|
| 中文支持 | ⭐⭐⭐⭐⭐ 原生 |
| 音色克隆 | 支持（3秒样本） |
| 内存需求 | ~1GB |
| 部署 | Docker |

### 3.2 kokoro-onnx 安装

```bash
pip install kokoro-onnx soundfile

# 下载模型
curl -L -o kokoro-v1.0.onnx "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
curl -L -o voices-v1.0.bin "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

# 使用
python
>>> from kokoro_onnx import Kokoro
>>> kokoro = Kokoro('kokoro-v1.0.onnx', 'voices-v1.0.bin')
>>> voices = kokoro.get_voices()
>>> samples, sr = kokoro.create("你好", voice=voices[0])
```

### 3.3 Edge TTS 安装

```bash
pip install edge-tts

# 使用命令行
edge-tts --voice "zh-CN-XiaoxiaoNeural" --text "你好" --write-media "output.mp3"
```

### 3.4 中文音色映射

**Edge TTS 音色**:

| 音色名称 | 性别 | 年龄感 | 适用 |
|---------|------|--------|------|
| zh-CN-XiaoxiaoNeural | 女 | 青年 | 女主角 |
| zh-CN-YunxiNeural | 男 | 青年 | 男主角 |
| zh-CN-XiaoyiNeural | 女 | 少年 | 女性少年角色 |
| zh-CN-YunyangNeural | 男 | 中年 | 成熟角色 |

**年龄-音色映射**:

```python
VOICE_AGE_MAP = {
    "childhood": {"female": "zh-CN-XiaoyiNeural", "male": "zh-CN-YunxiNeural"},
    "teen": {"female": "zh-CN-XiaoyiNeural", "male": "zh-CN-YunxiNeural"},
    "young_adult": {"female": "zh-CN-XiaoxiaoNeural", "male": "zh-CN-YunxiNeural"},
    "middle_age": {"female": "zh-CN-YunyangNeural", "male": "zh-CN-YunyangNeural"},
    "elderly": {"female": "zh-CN-YunyangNeural", "male": "zh-CN-YunyangNeural"}
}
```

---

## 4. 音频处理栈

### 4.1 依赖

```txt
pydub>=0.25.0        # 音频处理
soundfile>=0.12.0    # 音频I/O
numpy>=1.24.0        # 数值计算
```

### 4.2 核心操作

```python
from pydub import AudioSegment

# 加载音频
audio = AudioSegment.from_mp3("input.mp3")

# 拼接
combined = audio1 + audio2

# 淡入淡出
output = audio.fade_in(100).fade_out(100)

# 导出
output.export("output.mp3", format="mp3")
```

---

## 5. Web 框架栈

### 5.1 FastAPI 扩展

基于现有 `main.py`，添加新端点：

```python
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

app = FastAPI(title="book2audio")

class ConvertRequest(BaseModel):
    file_path: str
    chapters: list[int] | None = None
    voice_mapping: dict[str, str] | None = None
    output_format: str = "mp3"

@app.post("/api/convert")
async def convert_novel(request: ConvertRequest, background: BackgroundTasks):
    job_id = generate_job_id()
    background.add_task(process_conversion, job_id, request)
    return {"job_id": job_id, "status": "processing"}

@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    return get_job_status(job_id)
```

---

## 6. 容器化栈

### 6.1 Docker Compose

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ./models:/root/.ollama
    deploy:
      resources:
        limits:
          memory: 2G

  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - ollama
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
    volumes:
      - ./output:/app/output

  cosyvoice:
    image: cosyvoice:latest
    ports:
      - "5000:5000"
```

### 6.2 Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 7. 依赖清单

### 7.1 requirements.txt

```txt
# Core
fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0

# LLM
requests>=2.31.0

# TTS
edge-tts>=6.1.0

# Audio
pydub>=0.25.0
soundfile>=0.12.0

# Utils
python-multipart>=0.0.6
aiofiles>=23.0.0
```

### 7.2 可选依赖

```txt
# CosyVoice (本地TTS)
cosyvoice @ git+https://github.com/modelscope/CosyVoice.git

# Ollama Python SDK
ollama>=0.1.0

# 内存监控
psutil>=5.9.0
```

---

## 8. 系统要求

### 8.1 硬件要求

| 规格 | 最低 | 推荐 |
|------|------|------|
| 内存 | 4GB | 8GB+ |
| 存储 | 2GB | 5GB+ |
| CPU | 4核 | 8核 |
| GPU | 可选 | NVIDIA (加速TTS) |

### 8.2 内存预算

| 组件 | 内存占用 |
|------|---------|
| Qwen3-0.6B | ~600MB |
| CosyVoice | ~1GB |
| 应用代码 | ~200MB |
| **总计** | ~1.8GB |

### 8.3 软件要求

| 软件 | 版本 |
|------|------|
| Python | 3.10+ |
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| ffmpeg | 最新 |

---

## 9. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_BASE_URL` | http://localhost:11434 | Ollama API 地址 |
| `MODEL_NAME` | qwen3:0.6b | LLM 模型名称 |
| `TTS_ENGINE` | edge | TTS 引擎 (edge/cosyvoice) |
| `OUTPUT_DIR` | ./output | 音频输出目录 |
| `LOG_LEVEL` | INFO | 日志级别 |

---

## 10. 完整技术栈图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (User Layer)                       │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│   │   CLI       │  │   Web UI   │  │   API      │          │
│   │  book2audio │  │   未来扩展   │  │  REST/WSG  │          │
│   └─────────────┘  └─────────────┘  └─────────────┘          │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                        API 网关层                              │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              FastAPI (uvicorn) Port: 8000                │  │
│   │  /api/analyze  /api/convert  /api/tts  /api/voices     │  │
│   └─────────────────────────────────────────────────────────┘  │
└────────────────────────────┬───────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   文本处理层     │ │   LLM 推理层     │ │   TTS 合成层     │
│                 │ │                 │ │                 │
│ • TXT解析       │ │ • Qwen3-0.6B   │ │ • CosyVoice    │
│ • 章节分割      │ │ • Ollama API   │ │ • Edge TTS      │
│ • 对话提取      │ │ • 角色分析      │ │ • 音色映射       │
│ • 角色识别      │ │ • 画像提取      │ │ • 语音合成       │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        音频处理层                                │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│   │   pydub     │  │  soundfile  │  │   ffmpeg   │          │
│   │  音频拼接    │  │  音频I/O    │  │  格式转换    │          │
│   └─────────────┘  └─────────────┘  └─────────────┘          │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        输出层                                    │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│   │   MP3       │  │   M4A       │  │   WAV       │          │
│   │   输出       │  │   输出       │  │   输出       │          │
│   └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

*技术栈文档完成时间: 2026-05-09*
