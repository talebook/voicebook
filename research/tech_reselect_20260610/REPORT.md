# 技术选型重审报告（2026-06-10）

> 背景：上轮选型（2026-05-09）为 Qwen3-0.6B（角色分析）+ CosyVoice-300M-SFT（TTS）。
> 本轮目标：① 用**程序化方案**构建对话/说话人识别库，弱化对通用小 LLM 的依赖；② 选择**更有真人感**的 TTS。背景音降级为 P2，不在本轮范围。

---

## 一、识别侧：程序化识别库

### 1.1 思路转变

| | 旧方案 | 新方案 |
|---|---|---|
| 核心 | Qwen3-0.6B 通用 LLM 全包 | **规则引擎为主 + 专用小模型兜底** |
| 优点 | 实现简单 | 确定性高、可调试、快、便宜 |
| 缺点 | 0.6B 说话人归属准确率不可控、慢、幻觉 | 需要自建规则库 |

### 1.2 参考实现：easytts（直接可借鉴）

[easytts](https://github.com/Warma10032/easytts) 的流水线与我们的目标几乎一致：

```
正则分句（引号检测） → 对白/旁白切分 → RoBERTa 说话人识别 → 多音色 TTS
```

- 说话人识别模型：`chinese-roberta-wwm-ext-large-csi-v1`（HuggingFace）
- 训练数据：[yudiandoris/csi](https://github.com/yudiandoris/csi)（"End-to-End Chinese Speaker Identification", 基于《平凡的世界》等小说语料）
- 学术基础：[A Chinese Dataset for Identifying Speakers in Novels](https://www.isca-archive.org/interspeech_2019/chen19d_interspeech.html)（Interspeech 2019）

### 1.3 推荐的识别库分层架构

```
L1 规则层（覆盖 ~70-80%，零成本、确定性）
   ├── 引号对白提取：“”、「」、‘’ 等多格式
   ├── 显式归属："X说/道/问/答/喊…" 前后缀模式（动词表可枚举）
   └── 轮替推断：两人对话场景的交替归属
L2 专用模型层（规则无法判定时兜底）
   └── chinese-roberta-wwm-ext-large-csi（~325M 参数，fp16 约 650MB，仍满足 ≤1GB 约束）
L3 画像层（低频调用，每章/每角色一次）
   └── 保留 LLM 做角色画像（年龄/性别/气质→音色映射），不参与逐句归属
```

关键收益：逐句说话人归属（最高频调用）不再走 LLM，速度和确定性大幅提升；LLM 只做低频的画像提取。

### 1.4 验证方式

- 从《秦吏》（book.txt）抽 2-3 章人工标注 100-200 条对白作为金标集
- 指标：规则层覆盖率、L1+L2 整体归属准确率（目标 ≥90%，高于原 80% 目标）

---

## 二、TTS 侧：真人感优先

### 2.1 候选对比（2026-06 视角）

| 方案 | 真人感 | 中文 | 速度/资源 | 部署 | 备注 |
|------|--------|------|----------|------|------|
| **IndexTTS-2**（B站） | ⭐⭐⭐⭐⭐ 公认最接近真人 | 优秀（多音字+拼音纠音） | 慢（实测约为 CosyVoice3 的 9 倍耗时），fp16 需 ~8GB 显存，**需 NVIDIA CUDA** | 本地 GPU | 音色与情感解耦控制，适合多角色有声书 |
| **CosyVoice3-0.5B**（阿里） | ⭐⭐⭐⭐ | 优秀（18 种方言/口音） | 快（同测试快 ~9 倍），4-6GB | 本地，对 Mac 较友好 | 比上轮用的 CosyVoice-300M-SFT 有代际提升 |
| Fish Speech / OpenAudio S1 | ⭐⭐⭐⭐（TTS Arena ELO 顶级） | 好 | 中 | 本地 GPU | 克隆强 |
| F5-TTS | ⭐⭐⭐⭐ | 好 | 慢（diffusion） | 本地 GPU | |
| 火山引擎豆包 TTS（云 API） | ⭐⭐⭐⭐⭐ | 极佳，多情感音色丰富 | 快，无本地资源 | 云 API，按量计费 | 内部资源可能有优惠；非离线 |
| Edge TTS | ⭐⭐⭐ | 好 | 快，免费 | 云 API | 保留为草稿预览 |

实测对比参考：[CosyVoice3 vs IndexTTS2 hands-on](https://www.80aj.com/2025/12/17/showdown-cosyvoice3-vs-indextts2-a-hands-on-comparison-of-top-tts-models-en/)、[开源 TTS 2026 综述](https://findskill.ai/blog/best-open-source-tts-2026/)、[voice cloning 模型指南](https://www.siliconflow.com/articles/en/best-open-source-models-for-voice-cloning)

### 2.2 关键约束：本机是 macOS（无 CUDA）

IndexTTS-2 真人感最强但**强依赖 NVIDIA GPU**，本机无法跑。可行路径：

- **方案 A（推荐先行）**：本地 **CosyVoice3-0.5B**（Mac 可跑，4GB 级），真人感已比旧版 CosyVoice-300M-SFT 明显提升
- **方案 B（追求极致）**：远程 GPU（火山引擎/内部资源）部署 **IndexTTS-2**，离线批量渲染整本书
- **方案 C（最省事）**：**豆包 TTS 云 API**，真人感顶级 + 情感控制，代价是离线性和按量成本

有声书是**离线批量生产**场景，生成慢可接受 → 质量权重 > 速度权重，B/C 的真人感上限更高。

### 2.3 推荐决策

1. **主线**：CosyVoice3-0.5B 替换旧 CosyVoice-300M-SFT（接口相近，迁移成本低），先跑通端到端
2. **质量上限**：抽象 TTS 引擎接口，预留 IndexTTS-2（远程 GPU）与豆包 API 两个高质量后端，做同章节 ABX 盲听对比后定终选
3. Edge TTS 仅保留为快速预览

---

## 三、对原规划的影响

| 项 | 变更 |
|---|---|
| REQ-002/003/009（角色识别/对话分类/发言归属） | 实现方式改为 规则引擎 + CSI 专用模型，不再依赖 Qwen3-0.6B 逐句判断 |
| REQ-004（画像提取） | 保留 LLM，低频调用 |
| REQ-005（TTS） | CosyVoice-300M-SFT → **CosyVoice3-0.5B**，新增 IndexTTS-2 / 豆包 API 备选 |
| 新增（P2） | 背景音/环境音（不进入 v1.0） |
| 约束「LLM ≤1GB」 | 维持；CSI 模型 fp16 ~650MB 满足 |

## 四、下一步建议

1. 建 `src/attribution/` 识别库骨架：规则层（分句/引号/归属动词表）+ CSI 模型封装
2. 用《秦吏》前 3 章建金标集，量化规则层覆盖率
3. Mac 上装 CosyVoice3-0.5B，与旧版 CosyVoice 同文本 AB 对比真人感
