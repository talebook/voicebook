# book2audio 技术研究

## 1. LLM 模型研究（内存≤1GB）

### 1.1 候选模型对比

| 模型 | 参数量 | 量化后内存 | 中文支持 | 推荐度 |
|------|--------|-----------|---------|--------|
| **Qwen3-0.6B** | 0.6B | ~600MB (Q4) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Qwen2.5-0.5B** | 0.5B | ~500MB (Q4) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Qwen2.5-1.5B** | 1.5B | ~1GB (Q4) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Llama-3.2-1B** | 1B | ~700MB (Q4) | ⭐⭐⭐ | ⭐⭐⭐ |
| **Phi-3-mini** | 3.8B | ~2.5GB (Q4) | ⭐⭐⭐ | ❌ (超出限制) |

### 1.2 推荐方案

**首选**: Qwen3-0.6B（已有项目基础）

```
Ollama 模型名: qwen3:0.6b
内存占用: ~600MB (FP16)
推理速度: 快速（CPU可运行）
中文能力: 优秀
```

**备选**: Qwen2.5-0.5B

```
Ollama 模型名: qwen2.5:0.5b
内存占用: ~500MB (FP16)
推理速度: 更快
中文能力: 优秀
```

### 1.3 Ollama 部署命令

```bash
# 拉取模型
ollama pull qwen3:0.6b

# 或轻量版
ollama pull qwen2.5:0.5b

# 运行测试
ollama run qwen3:0.6b "分析以下角色: 张三是个青年男子..."
```

---

## 2. TTS 模型研究

### 2.1 候选方案对比

| 方案 | 音色数量 | 中文支持 | 内存需求 | 部署 | 推荐度 |
|------|---------|---------|---------|------|--------|
| **CosyVoice-300M** | 10+预设+克隆 | ⭐⭐⭐⭐⭐ 原生 | ~1GB | 本地 | ⭐⭐⭐⭐⭐ |
| **Coqui XTTS v2** | 克隆+预设 | 需微调 | ~2GB | 本地 | ⭐⭐⭐⭐ |
| **Edge TTS** | 10+音色 | ⭐⭐⭐⭐⭐ | 无 | 云API | ⭐⭐⭐⭐ |
| **GPT-SoVITS** | 克隆能力 | 需训练 | ~3GB | 本地 | ⭐⭐⭐ |
| **VALL-E X** | 克隆 | 支持 | ~3GB | 本地 | ⭐⭐⭐ |

### 2.2 CosyVoice（推荐）

**来源**: 阿里通义实验室开源

**优势**:
- 300M 参数，轻量级
- 原生中文支持，无需微调
- 支持 3 秒音色克隆
- 支持情感控制
- 覆盖多种方言（四川话等）

**安装**:

```bash
pip install cosyvoice
# 或通过 ModelScope
```

**使用示例**:

```python
from cosyvoice import CosyVoice

cosyvoice = CosyVoice('cosyvoice-300m')
# 使用预设音色
output = cosyvoice.inference('你好，欢迎收听有声书。', spk='zh-CN-XiaoxiaoNeural')
# 或克隆音色
output = cosyvoice.inference('文本', ref_audio='参考音频.wav')
```

### 2.3 Coqui XTTS v2

**优势**:
- 支持 17 种语言
- 零样本音色克隆
- 开源社区活跃（HuggingFace 下载 >500万）

**劣势**:
- 中文需微调
- 内存需求较高（~2GB）

**安装**:

```bash
pip install TTS
```

### 2.4 Edge TTS（快速原型）

**优势**:
- 微软免费 API
- 无需本地部署
- 中文音色质量好
- 支持多种中文音色

**劣势**:
- 需要网络连接
- 无法克隆自定义音色

**使用**:

```bash
# 安装 edge-tts
pip install edge-tts

# 使用示例
edge-tts --voice "zh-CN-XiaoxiaoNeural" --text "你好" --write-media "output.mp3"
```

**可用中文音色**:

| 音色名称 | 性别 | 年龄感 |
|---------|------|--------|
| zh-CN-XiaoxiaoNeural | 女 | 青年 |
| zh-CN-YunxiNeural | 男 | 青年 |
| zh-CN-XiaoyiNeural | 女 | 少年 |
| zh-CN-YunyangNeural | 男 | 中年 |

---

## 3. 年龄-音色映射方案

### 3.1 Edge TTS 音色映射

```python
VOICE_MAP = {
    # 童年 (5-12岁)
    "childhood": {
        "female": "zh-CN-XiaoxiaoNeural",   # 稍显稚嫩
        "male": "zh-CN-YunxiNeural"
    },
    # 少年 (13-17岁)
    "teen": {
        "female": "zh-CN-XiaoyiNeural",    # 少女音色
        "male": "zh-CN-YunxiNeural"
    },
    # 青年 (18-35岁)
    "young_adult": {
        "female": "zh-CN-XiaoxiaoNeural",  # 成熟女声
        "male": "zh-CN-YunxiNeural"
    },
    # 中年 (36-55岁)
    "middle_age": {
        "female": "zh-CN-YunyangNeural",    # 知性女声
        "male": "zh-CN-YunyangNeural"
    },
    # 老年 (55+)
    "elderly": {
        "female": "zh-CN-YunyangNeural",   # 沉稳
        "male": "zh-CN-YunyangNeural"
    }
}
```

### 3.2 CosyVoice 音色选择

CosyVoice 提供更自然的音色切换，支持通过参数控制：

```python
# 音色切换通过参考音频实现
# 年轻男性参考 → 年龄感年轻的输出
# 年长男性参考 → 年龄感成熟的输出

voice_config = {
    "childhood": {"ref": "child_male_ref.wav"},
    "teen": {"ref": "teen_male_ref.wav"},
    "young_adult": {"ref": "adult_male_ref.wav"},
    "middle_age": {"ref": "middle_male_ref.wav"},
    "elderly": {"ref": "elderly_male_ref.wav"}
}
```

---

## 4. 完整技术栈总结

### 4.1 推荐技术栈

| 层级 | 方案 | 说明 |
|------|------|------|
| **LLM** | Qwen3-0.6B via Ollama | 内存 ~600MB，中文优秀，已有基础 |
| **TTS** | CosyVoice-300M | 本地部署，原生中文，支持克隆 |
| **备选TTS** | Edge TTS | 快速原型，无需部署 |
| **音频处理** | pydub + soundfile | 音频拼接、格式转换 |
| **后端** | FastAPI (已有) | 扩展现有服务 |

### 4.2 内存预算

| 组件 | 内存占用 |
|------|---------|
| Qwen3-0.6B | ~600MB |
| CosyVoice-300M | ~1GB |
| 应用代码 | ~200MB |
| **总计** | ~1.8GB |

### 4.3 GPU 需求

| 场景 | GPU 需求 | 说明 |
|------|---------|------|
| CPU 推理 | 0 | Qwen3-0.6B 可 CPU 运行 |
| GPU 加速 | 推荐 | 加速 TTS 推理 |
| 最低配置 | 无 GPU | 可运行，性能较慢 |

---

## 5. 开源项目参考

### 5.1 类似项目

1. ** audiobook-generation - 完整的有声书生成流水线
2. ** llm-tts-pipeline - LLM + TTS 集成示例
3. ** cosyvoice-webui - CosyVoice Web 界面

### 5.2 关键开源组件

- **textract**: 多种格式文本提取
- **pypandoc**: 文档格式转换
- **gtts**: Google TTS（备用）
- **pydub**: 音频处理

---

*研究完成时间: 2026-05-09*
