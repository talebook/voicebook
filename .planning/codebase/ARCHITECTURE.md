# 项目架构文档 (ARCHITECTURE.md)

## 1. 项目概述

**项目名称**: book2audio
**项目定位**: 小说角色文本画像识别系统
**核心功能**: 基于 Qwen3-0.6B 大语言模型，对小说章节内容进行角色画像分析，提取角色的年龄阶段、外貌特征、气质性格、音色描述、情绪状态和重要变化等信息，用于支持有声书项目的动态 TTS（文本转语音）合成。

**应用场景**:
- 有声书制作：根据角色年龄和情绪动态调整语音参数
- 角色发展追踪：跨章节追踪角色从少年到老年的变化
- 音频角色匹配：为不同角色匹配适合的音色

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (User Layer)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   CLI 测试脚本   │  │   FastAPI 服务   │  │   Docker 容器    │  │
│  │  test_demo.py   │  │     main.py     │  │  docker-compose  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
└───────────┼─────────────────────┼─────────────────────┼───────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      接口层 (API Layer)                           │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  POST /analyze          - 分析章节角色画像                    │ │
│  │  GET  /character/{name}/arc - 获取角色发展轨迹               │ │
│  │  GET  /health           - 健康检查                          │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     核心业务层 (Business Layer)                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              NovelCharacterProfiler 类                       │ │
│  │  ├── analyze_chapter()      - 章节分析主入口                  │ │
│  │  ├── _analyze_character()   - 单角色分析                     │ │
│  │  ├── _parse_response()      - JSON 响应解析                  │ │
│  │  ├── get_character_arc()    - 获取角色发展轨迹                │ │
│  │  └── character_history      - 角色历史状态管理                │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    数据模型 (Data Models)                     │ │
│  │  ├── CharacterProfile     - 角色画像数据类                    │ │
│  │  └── CharacterHistory      - 角色历史记录                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     模型层 (Model Layer)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Ollama     │  │ ModelScope   │  │ HuggingFace  │          │
│  │  API 调用     │  │ SDK 加载     │  │ Transformers │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                 Qwen3-0.6B 语言模型                          │ │
│  │  - 0.6B 参数量，~523MB 模型大小                              │ │
│  │  - 40K 上下文窗口                                            │ │
│  │  - 支持中文理解与生成                                        │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker 网络 (novel-network)              │
│                                                              │
│  ┌─────────────────────┐      ┌─────────────────────────┐  │
│  │    ollama 服务        │      │    FastAPI 服务 (api)    │  │
│  │  端口: 11434          │◄────►│  端口: 8000              │  │
│  │  模型: qwen3:0.6b    │      │  依赖: ollama           │  │
│  │  存储: ./models      │      │  存储: ./app, ./data    │  │
│  └─────────────────────┘      └─────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块设计

### 3.1 角色画像分析器 (NovelCharacterProfiler)

**职责**: 核心业务逻辑，处理角色画像的生成和管理。

**关键属性**:
- `base_url`: Ollama API 基础 URL
- `model`: 模型名称
- `character_history`: Dict[str, CharacterHistory] - 所有角色的历史记录

**关键方法**:

| 方法 | 描述 | 输入 | 输出 |
|------|------|------|------|
| `analyze_chapter()` | 分析章节中多个角色 | 章节号、内容、角色列表 | Dict[str, CharacterProfile] |
| `_analyze_character()` | 分析单个角色 | 章节号、内容、角色名、历史状态 | CharacterProfile |
| `_parse_response()` | 解析 LLM JSON 响应 | 原始响应文本 | CharacterProfile |
| `get_character_arc()` | 获取角色发展轨迹 | 角色名 | Dict (含所有章节画像) |
| `call_llm()` | 调用 LLM API | prompt | str (原始响应) |

### 3.2 数据模型

#### CharacterProfile (角色画像)
```python
@dataclass
class CharacterProfile:
    name: str                    # 角色名称
    chapter: int                 # 章节号
    age_stage: str               # 年龄阶段
    appearance: str              # 外貌特征
    temperament: str              # 气质性格
    voice_description: str       # 音色描述
    emotional_state: str         # 情绪状态
    key_changes: str             # 重要变化
    confidence: float = 0.0      # 置信度
    timestamp: str = ""          # 分析时间戳
```

#### CharacterHistory (角色历史)
```python
@dataclass
class CharacterHistory:
    name: str
    profiles: Dict[int, CharacterProfile]  # 章节号 -> 画像

    def add_profile()           # 添加画像
    def get_profile()           # 获取指定章节画像（支持回溯）
    def get_latest_profile()    # 获取最新画像
```

### 3.3 Prompt 设计

**系统提示词模板**:
```
分析以下小说章节中角色「{character_name}」的状态。

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

直接输出JSON，不要有其他内容。
```

**LLM 生成参数**:
```python
{
    "temperature": 0.3,        # 低温度保证稳定性
    "num_predict": 512,         # 最大 token 数
    "stop": ["```", "```json"]  # 停止词
}
```

---

## 4. 数据流分析

### 4.1 章节分析流程

```
用户输入
    │
    ▼
┌─────────────────┐
│ 输入验证         │
│ - 章节号         │
│ - 章节内容       │
│ - 角色列表       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 角色循环处理     │
│ (逐个分析)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│ 加载历史画像     │────►│ 构建增强 Prompt  │
│ (如有)          │     │ + 历史状态参考    │
└─────────────────┘     └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ 调用 LLM API     │
                         │ (Ollama/本地)    │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ 解析 JSON 响应   │
                         │ (容错处理)       │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ 更新历史记录     │
                         │ (character_history) │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ 返回分析结果     │
                         └─────────────────┘
```

### 4.2 响应解析流程

```python
def _parse_response(raw_response):
    # 1. 清理 markdown 代码块
    if "```json" in response:
        response = split("```json")[-1].split("```")[0]

    # 2. 提取 JSON 对象
    start = response.find('{')
    end = response.rfind('}') + 1

    # 3. 解析并映射到 CharacterProfile
    return CharacterProfile(...)
```

---

## 5. 多模型支持

项目支持三种模型加载方式：

| 加载方式 | 文件 | 适用场景 | 依赖 |
|---------|------|---------|------|
| **Ollama API** | test_demo.py | 生产环境、Docker 部署 | requests |
| **ModelScope SDK** | test_modelscope.py, test_ms.py | 国内网络加速 | modelscope, transformers |
| **HuggingFace** | test_qwen3.py, test_final.py | 标准 HF 环境 | transformers |

---

## 6. 扩展方向

### 6.1 已规划功能
1. **多章节批量处理**: 自动化追踪角色年龄变化
2. **TTS 集成**: 与 KOROO TTS 系统对接
3. **年龄变化追踪**: 可视化展示角色人生轨迹

### 6.2 潜在扩展
1. 角色关系图谱分析
2. 情感趋势图表生成
3. 多角色对话场景分离
4. 旁白与对话自动识别

---

## 7. 项目文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| main.py | 核心 | FastAPI 服务 + 核心业务逻辑 |
| test_demo.py | 测试 | Ollama API 调用测试 |
| test_modelscope.py | 测试 | ModelScope 镜像加载测试 |
| test_qwen3.py | 测试 | HuggingFace transformers 加载测试 |
| test_final.py | 测试 | 最终版测试（含思考链禁用） |
| test_ms.py | 测试 | ModelScope SDK 加载测试 |
| full_book_demo.py | 示例 | 整本小说关键章节分析示例 |
| docker-compose.yml | 配置 | Docker 编排配置 |
| Dockerfile | 配置 | FastAPI 服务镜像 |

---

## 8. 配置文件

### 8.1 docker-compose.yml
- **ollama 服务**: 模型运行容器，端口 11434
- **api 服务**: FastAPI 应用，端口 8000

### 8.2 Dockerfile
- 基础镜像: python:3.10-slim
- 依赖: fastapi, uvicorn, requests, pydantic
- 启动命令: uvicorn main:app --host 0.0.0.0 --port 8000
