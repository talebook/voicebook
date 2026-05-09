# 技术栈文档 (STACK.md)

## 1. 技术栈概览

| 层级 | 技术选型 | 版本/规格 |
|------|---------|----------|
| **运行时** | Python | 3.10+ |
| **Web 框架** | FastAPI | 最新稳定版 |
| **AI 模型** | Qwen3-0.6B | 0.6B 参数，40K 上下文 |
| **模型部署** | Ollama / HuggingFace Transformers / ModelScope | 多后端支持 |
| **容器化** | Docker + Docker Compose | 容器编排 |
| **HTTP 客户端** | requests / httpx | API 调用 |
| **数据验证** | Pydantic | 数据模型定义 |

---

## 2. 核心依赖

### 2.1 Python 包依赖

```
fastapi>=0.100.0          # Web 框架
uvicorn>=0.23.0           # ASGI 服务器
pydantic>=2.0.0           # 数据验证
requests>=2.31.0           # HTTP 客户端
torch>=2.0.0              # PyTorch 深度学习框架
transformers>=4.35.0      # HuggingFace 模型库
modelscope>=1.9.0         # 魔搭 SDK（可选，国内加速）
```

### 2.2 依赖版本约束

| 包名 | 最低版本 | 推荐版本 | 用途 |
|------|---------|---------|------|
| python | 3.10 | 3.10-slim | 运行时环境 |
| fastapi | 0.100 | 最新 | API 框架 |
| pydantic | 2.0 | 2.x | 数据模型 |
| torch | 2.0 | 2.0+ | 模型推理 |
| transformers | 4.35 | 4.35+ | 模型加载 |

---

## 3. AI/ML 技术栈

### 3.1 大语言模型

**模型**: Qwen3-0.6B

| 规格 | 值 |
|------|-----|
| 参数量 | 0.6B (6亿) |
| 模型大小 | ~523MB |
| 上下文窗口 | 40K tokens |
| 量化支持 | 支持 |
| 部署方式 | Ollama / 本地 / API |

**模型来源**:
- HuggingFace: `Qwen/Qwen3-0.6B`
- ModelScope: `Qwen/Qwen3-0.6B`
- Ollama: `qwen3:0.6b`

### 3.2 模型加载方式对比

| 方式 | 优势 | 劣势 | 适用场景 |
|------|------|------|----------|
| **Ollama** | 一键部署、API 简单 | 需额外安装 | 生产环境 |
| **HuggingFace Transformers** | 原生 API、灵活 | 需配置 HF 访问 | 标准开发 |
| **ModelScope** | 国内加速 | 依赖魔搭 | 国内网络 |

### 3.3 模型推理参数

```python
# Ollama API
{
    "model": "qwen3:0.6b",
    "prompt": "<prompt>",
    "stream": False,
    "options": {
        "temperature": 0.3,      # 生成温度
        "num_predict": 512,       # 最大 token 数
        "stop": ["```", "```json"]
    }
}

# Transformers
{
    "max_new_tokens": 400,
    "temperature": 0.3,
    "top_p": 0.9,
    "do_sample": True
}
```

---

## 4. Web 框架栈

### 4.1 FastAPI 路由设计

```
/
├── POST /analyze                    # 章节角色分析
│   ├── Request: ChapterAnalyzeRequest
│   └── Response: ChapterAnalyzeResponse
│
├── GET  /character/{char_name}/arc # 角色发展轨迹
│   └── Response: Dict (角色历史)
│
└── GET  /health                     # 健康检查
    └── Response: Dict (服务状态)
```

### 4.2 FastAPI 特性使用

- **异步支持**: async/await 语法
- **数据验证**: Pydantic BaseModel
- **自动文档**: OpenAPI/Swagger
- **类型提示**: 完整的类型标注

---

## 5. 容器化技术栈

### 5.1 Docker 配置

**Dockerfile**:
```dockerfile
FROM python:3.10-slim
WORKDIR /app
RUN pip install fastapi uvicorn requests pydantic
COPY app /app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml**:
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ./models:/root/.ollama

  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - ollama
```

### 5.2 容器资源

| 服务 | 镜像 | 端口 | 存储 |
|------|------|------|------|
| ollama | ollama/ollama:latest | 11434 | ./models |
| api | book2audio-api | 8000 | ./app, ./data |

---

## 6. 开发工具栈

### 6.1 代码质量

| 工具 | 用途 | 配置 |
|------|------|------|
| Python | 语言 | 3.10+ |
| type hints | 类型检查 | 内置 |
| dataclasses | 数据建模 | 内置 |
| pydantic | 数据验证 | v2 |

### 6.2 测试框架

| 工具 | 用途 |
|------|------|
| pytest | 单元测试 |
| requests | HTTP 测试 |

### 6.3 开发环境

| 组件 | 推荐配置 |
|------|----------|
| Python | 3.10+ |
| 内存 | 4GB+ (模型推理) |
| GPU | NVIDIA GPU (可选，加速推理) |

---

## 7. 网络与 API

### 7.1 内部 API

**Ollama API**:
```
POST http://ollama:11434/api/generate
POST http://ollama:11434/api/pull
GET  http://ollama:11434/api/tags
```

### 7.2 外部 API

**用户接口**:
```
POST http://localhost:8000/analyze
GET  http://localhost:8000/character/{name}/arc
GET  http://localhost:8000/health
```

---

## 8. 依赖管理

### 8.1 当前项目无 requirements.txt

项目依赖直接在 Dockerfile 中定义：
```dockerfile
RUN pip install --no-cache-dir fastapi uvicorn requests pydantic
```

### 8.2 建议的 requirements.txt

```txt
fastapi>=0.100.0
uvicorn>=0.23.0
requests>=2.31.0
pydantic>=2.0.0
torch>=2.0.0
transformers>=4.35.0
modelscope>=1.9.0
```

---

## 9. 系统要求

### 9.1 硬件要求

| 规格 | 最低 | 推荐 |
|------|------|------|
| 内存 | 4GB | 8GB+ |
| 存储 | 1GB | 2GB+ |
| CPU | 4 核 | 8 核 |
| GPU | 可选 | NVIDIA (加速) |

### 9.2 软件要求

| 软件 | 版本 |
|------|------|
| Python | 3.10+ |
| Docker | 20.10+ |
| Docker Compose | 2.0+ |

---

## 10. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| OLLAMA_BASE_URL | http://ollama:11434 | Ollama API 地址 |
| MODEL_NAME | qwen3:0.6b | 模型名称 |
| HF_ENDPOINT | https://modelscope.cn | HF 镜像 (可选) |

---

## 11. 技术栈总结图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端/客户端                                │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│   │  curl/HTTP  │  │   浏览器     │  │   Python    │          │
│   │    调用      │  │  (Swagger)   │  │   脚本       │          │
│   └─────────────┘  └─────────────┘  └─────────────┘          │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                        API 网关层                                │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                 FastAPI (uvicorn)                        │  │
│   │                 Port: 8000                               │  │
│   └─────────────────────────────────────────────────────────┘  │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                        模型推理层                                │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│   │   Ollama     │  │ Transformers │  │  ModelScope  │          │
│   │   Server     │  │   Library    │  │     SDK      │          │
│   └──────────────┘  └──────────────┘  └──────────────┘          │
│                             │                                    │
│                    ┌────────▼────────┐                          │
│                    │  Qwen3-0.6B    │                          │
│                    │    Model       │                          │
│                    └────────────────┘                          │
└────────────────────────────┬───────────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────────┐
│                        基础设施层                                │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│   │    Docker    │  │     CPU      │  │     GPU      │          │
│   │  Container   │  │   (torch)   │  │   (CUDA)     │          │
│   └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```
