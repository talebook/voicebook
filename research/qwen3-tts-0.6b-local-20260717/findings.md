# Qwen3-TTS 0.6B 在本机运行的资源与速度评估

日期：2026-07-17

## 结论

本机是 **MacBook Air（M2，8 核 CPU、8 核 GPU、16 GB 统一内存）**。Qwen3-TTS 0.6B 可以作为本地单路推理的候选，但 Qwen 没有发布 Apple Silicon 性能或内存数字，不能把官方 CUDA/vLLM 成绩直接套到这台 Mac 上。

针对 voicebook-tool 当前“多个预置音色配角色”的用途，应先试 `Qwen3-TTS-12Hz-0.6B-CustomVoice`：

- 模型快照精确占用 **2,498,388,392 bytes（2.498 GB / 2.327 GiB）**。
- 实际安装建议至少预留 **5 GiB**，更稳妥地预留 **8 GiB**，包含模型、Python/PyTorch 依赖、下载缓存与中间文件。本机数据卷当前约剩 **22 GiB**，装一个 checkpoint 足够，但不宜同时留多份模型和大批量 WAV 中间文件。
- 权重常驻内存的理论下限是 **2.327 GiB**。工程估算单路推理常用工作集约 **4–6 GiB**，峰值按 **6–8 GiB** 留余量；这是估算，不是官方实测值。16 GB 统一内存预计能跑单路，但不建议多进程并发加载模型。
- 本机 PyTorch 2.12.0 的 MPS 与 BF16 矩阵运算已通过最小检查，Metal 给出的推荐 GPU 工作集上限是 **12,713,115,648 bytes（11.84 GiB）**。基础条件满足。
- 官方没有提供 M2 的 RTF。容量规划时可先用 **RTF 0.8–2.0** 作为保守试跑区间，而不是承诺值；即合成 1 小时音频暂按约 **48–120 分钟**估算，最终必须用实际书稿跑基准。

## 官方事实

### 1. 模型存储

| Checkpoint | 主模型 | 内置 speech tokenizer | 完整快照 |
| --- | ---: | ---: | ---: |
| 0.6B-CustomVoice | 1,811,626,576 B | 682,293,092 B | 2,498,388,392 B / 2.327 GiB |
| 0.6B-Base | 1,829,344,272 B | 682,293,092 B | 2,516,106,051 B / 2.343 GiB |

数字来自 Qwen 官方 Hugging Face API 的逐文件 `size` 字段求和：[CustomVoice 文件 API](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/tree/main?recursive=true&expand=true)、[Base 文件 API](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base/tree/main?recursive=true&expand=true)。官方文件页也将 CustomVoice 快照显示为约 2.5 GB：[文件树](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice/tree/main)。

Hugging Face 模型卡将这个“0.6B” checkpoint 统计为 **0.9B parameters、BF16**；此外快照还内置约 682 MB 的 speech tokenizer。因此“0.6B”是系列规格名，不能理解成完整 TTS 管线只有 0.6B 参数或只占约 1.2 GB：[官方模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)。

### 2. 官方速度

Qwen 技术报告在内部 vLLM V0 环境中，对 12Hz 0.6B 给出的流式成绩是：

| 并发 | 首包延迟 | RTF | 等价生成速度 |
| ---: | ---: | ---: | ---: |
| 1 | 97 ms | 0.288 | 约 3.47 倍实时 |
| 3 | 179 ms | 0.338 | 约 2.96 倍实时 |
| 6 | 299 ms | 0.434 | 约 2.30 倍实时 |

来源：[Qwen3-TTS Technical Report，§3.4 / Table 2](https://arxiv.org/html/2601.15621#S3.SS4)。

必须保留报告里的限定：这些数字来自 Qwen 的内部 vLLM 引擎、单个未披露型号的“typical computational resource”，并对 tokenizer decoder 使用了 `torch.compile` 和 CUDA Graph。报告没有披露 GPU 型号、显存、操作系统，也没有 MPS 测试。因此 **RTF 0.288 不是这台 M2 的预期成绩**。

Qwen 官方仓库、模型卡和技术报告均未发布：

- 0.6B 的峰值 RAM/显存；
- Apple M1/M2/M3/M4 的 RTF；
- 与 EdgeTTS 的端到端同条件对比。

### 3. macOS / MPS 兼容性

官方项目要求 Python `>=3.9`，README 推荐干净的 Python 3.12 环境；固定依赖包括 `transformers==4.57.3`、`accelerate==1.12.0`，并依赖 torchaudio、soundfile、onnxruntime 等：[官方 pyproject.toml](https://github.com/QwenLM/Qwen3-TTS/blob/main/pyproject.toml)、[环境安装说明](https://github.com/QwenLM/Qwen3-TTS#environment-setup)。

兼容性证据需要分两层看：

1. PyTorch 和 Apple 官方说明，Apple Silicon 可通过 MPS 后端使用 Metal GPU 加速：[Apple 的 PyTorch on Metal 说明](https://developer.apple.com/metal/pytorch/)、[PyTorch MPS 文档](https://docs.pytorch.org/docs/stable/mps.html)。
2. Qwen 官方源码在旋转位置编码处显式识别 `mps`，避免对 MPS 使用不合适的 autocast device type；CLI 的 `--device` 会原样传给 `device_map`：[12Hz tokenizer 源码](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py#L272)、[主模型源码](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/core/models/modeling_qwen3_tts.py#L552)、[CLI 源码](https://github.com/QwenLM/Qwen3-TTS/blob/main/qwen_tts/cli/demo.py#L91-L102)。这说明源码考虑过 MPS，但官方 README 的所有完整示例仍是 CUDA，Qwen 没有给出 Apple Silicon 的支持承诺或性能数字。

FlashAttention 2 官方支持 CUDA 和 ROCm，没有 Metal/MPS 后端：[FlashAttention 官方仓库](https://github.com/Dao-AILab/flash-attention#installation-and-features)。所以本机试跑应使用类似下面的组合，而不是照抄 CUDA 示例：

```bash
qwen-tts-demo Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice \
  --device mps \
  --dtype bfloat16 \
  --no-flash-attn
```

这是根据官方 CLI 参数和本机能力推导出的试跑命令，不是 Qwen 官方发布的 Mac 配方。若遇到未实现的 MPS 算子，可用 PyTorch 官方的 `PYTORCH_ENABLE_MPS_FALLBACK=1` 让该算子回落 CPU，但速度可能明显下降：[MPS 环境变量](https://docs.pytorch.org/docs/stable/mps_environment_variables.html)。

### 4. 本机核验

2026-07-17 在本机执行只读检查：

```text
Model Name: MacBook Air
Model Identifier: Mac14,2
Chip: Apple M2
CPU: 8 cores (4 performance + 4 efficiency)
GPU: 8 cores
Memory: 16 GB
Architecture: arm64
Free disk: about 22 GiB

PyTorch: 2.12.0
torch.backends.mps.is_built(): True
torch.backends.mps.is_available(): True
BF16 MPS matmul: passed
torch.mps.recommended_max_memory(): 12,713,115,648 B (11.84 GiB)
```

Apple 的该机型技术规格确认 M2 具有 8 核 CPU、8 核 GPU 和 100 GB/s 统一内存带宽：[MacBook Air (M2, 2022) 技术规格](https://support.apple.com/en-ie/111867)。PyTorch 将 `recommended_max_memory()` 定义为 Metal 推荐的最大 GPU 工作集大小：[PyTorch API](https://docs.pytorch.org/docs/stable/generated/torch.mps.recommended_max_memory.html)。

## 工程估算

### 存储

官方唯一能精确给出的数字是模型 snapshot 2.327 GiB。下面是本项目的部署预算，不是官方承诺：

| 项目 | 预算 |
| --- | ---: |
| CustomVoice checkpoint | 2.327 GiB（精确） |
| Python / PyTorch / Qwen 运行依赖 | 约 0.8–1.5 GiB（估算，取决于现有环境与 wheel） |
| Hugging Face / uv 下载缓存、临时文件 | 约 1–3 GiB（估算，可清理） |
| 建议最低空闲量 | 5 GiB |
| 建议安全空闲量 | 8 GiB |

如果同时下载 CustomVoice 和 Base，两个官方快照原始合计约 **4.67 GiB**。当前需求只需要预置角色音色时没有必要同时装 Base；Base 的用途是用参考音频做 3 秒快速克隆：[官方模型列表](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)。

### 内存

内存下限由 2.327 GiB BF16 权重决定；实际还需要 KV cache、激活、tokenizer decoder、PyTorch/MPS 缓存、Python 运行时和音频缓冲。基于权重大小和单路推理结构给出的规划值是：

- 常见工作集：**4–6 GiB**；
- 峰值安全预算：**6–8 GiB**；
- 16 GB 统一内存机器：建议单模型、单生成队列；浏览器、IDE 和其他大进程会与 MPS 争用同一统一内存；
- 不要按章节启动多个模型进程。并发应在同一模型进程里批处理，而且必须先测峰值。

这些是容量估算。Qwen 没公布官方 0.6B 峰值内存，只有下载权重本身可以精确计算。

### 与 EdgeTTS 的速度关系

本项目已有 EdgeTTS 短句评测基线：中位数 **RTF 0.425**，约 2.35 倍实时，见 [`research/fanren_edge_runtime_estimate_20260616/REPORT.md`](../fanren_edge_runtime_estimate_20260616/REPORT.md)。这是项目实测，不是 Microsoft/Edge 官方性能承诺。

| 数据 | RTF | 生成 1 小时音频 | 可否直接比较 |
| --- | ---: | ---: | --- |
| Qwen 官方内部 CUDA/vLLM，0.6B 并发 1 | 0.288 | 17.3 分钟 | 不可外推到 M2 |
| 本项目 EdgeTTS 短句中位数 | 0.425 | 25.5 分钟 | 受网络、限流与切片长度影响 |
| M2 本地 Qwen 规划区间，未实测 | 0.8–2.0 | 48–120 分钟 | 仅用于排期 |

若错误地把 Qwen 的内部 CUDA 数字与本项目 Edge 实测硬比，Qwen 会显得快约 `0.425 / 0.288 = 1.48` 倍；这个比值对 M2 没有预测意义。由于本机不能使用 FlashAttention 2，也没有论文中的 CUDA Graph/vLLM 环境，更安全的上线假设是：**M2 本地 0.6B 初版会比当前 EdgeTTS 慢，暂按约 1.9–4.7 倍耗时排期，待同文本基准后替换。**

建议用同一批 10 个片段（短对白、中对白、长旁白各覆盖）测：

1. 冷启动模型加载时间；
2. 首段延迟；
3. `RTF = 生成耗时 / 音频时长`；
4. `torch.mps.driver_allocated_memory()` 峰值；
5. 连续生成 30 分钟后的持续速度，观察无风扇 MacBook Air 的长时负载变化。

只有这组目标机数据才能回答“比 EdgeTTS 快/慢多少”。

## 对 voicebook-tool 的额外影响

0.6B-CustomVoice 官方只提供 **9 个预置音色**，不是当前第三方 API 暴露的数十个音色：Vivian、Serena、Uncle_Fu、Dylan（北京方言）、Eric（四川方言）、Ryan、Aiden、Ono_Anna、Sohee。它支持 10 种语言；0.6B-Base 则用于参考音频克隆：[CustomVoice 使用说明与音色表](https://github.com/QwenLM/Qwen3-TTS#custom-voice-generate)、[Base voice clone](https://github.com/QwenLM/Qwen3-TTS#voice-clone)。

因此，切到本地 0.6B 后，现有“很多音色自动分配”的设计必须调整为以下二选一：

- 只在 9 个官方 CustomVoice 音色中分配，角色多时必然复用；
- 用 0.6B-Base 加项目自备的合法参考音频做克隆，并管理参考音频资产。

CustomVoice 官方模型卡给出了 `instruct` 风格引导词示例，包括“用特别愤怒的语气说”：[0.6B-CustomVoice 模型卡](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)。不过官方技术报告 Table 1 对 0.6B 的 Instruction Following 留空，和 checkpoint 模型卡存在口径不一致；工程实现应以该具体 checkpoint 的冒烟测试为准。

