# Voicebook TTS 调研总汇总

日期：2026-06-16

## 当前结论

主线建议：

1. **EdgeTTS 用作快速预览和整书草稿生产**：速度足够，单章分钟级，整本《凡人》预计 2.5 到 3 天，保守预留 5 到 6 天。
2. **CosyVoice3 用作高表现力样例和关键对白精修**：情绪控制最好，但本机 CPU 太慢，不适合整书量产。普通单章约 1.8 小时；《凡人》全对白约 45 到 67 天。
3. **Kokoro v1.1 只能按官方 `KPipeline(lang_code="z")` 路径评估中文**：ONNX 直跑和官方 HF demo 不等价；当前公开推理包不支持从 wav 训练/生成 Kokoro voice-pack。
4. **IndexTTS2/B 站路线保留为远程 GPU 候选**：没有官方 ONNX 版本；本机没有 CUDA/MPS 和 git-lfs/checkpoints，未生成公平样例。它的情绪/音色解耦能力仍是最强候选之一。
5. **工程优先级**：先让 EdgeTTS 跑通全书生产、断点续跑和大段切块；再把 CosyVoice 接到重点对白/角色样例；高质量量产再评估远程 GPU IndexTTS2 或云 TTS。

## 关键数字

### 《凡人》整书规模

| 指标 | 数值 |
| --- | ---: |
| EPUB 章节 HTML | 2,502 |
| 全书汉字 | 6,634,162 |
| 引号对白 | 43,188 段 |
| 对白汉字 | 1,647,452 |
| 对白占比 | 24.8% |

来源：`../fanren_cosy_dialogue_estimate_20260615/estimate.json`、`../fanren_edge_runtime_estimate_20260616/estimate.json`

### 整书生产耗时

| 场景 | CosyVoice3 本机 CPU | EdgeTTS 并发 4 |
| --- | ---: | ---: |
| 只生成所有对白 | 45 到 67 天 | 约 15.6 小时，保守 1 到 1.5 天 |
| 整本书含旁白 | 未建议本机执行，预计数月级 | 约 2.7 天，保守 5 到 6 天 |

### 单章节耗时

普通正文单章约 2,600 到 2,800 汉字：

| 口径 | CosyVoice3 本机 CPU | EdgeTTS 并发 4 |
| --- | ---: | ---: |
| 单章整章含旁白 | 约 1.8 小时 | 约 1.3 分钟 |
| 单章只生成对白 | 约 20 到 25 分钟 | 约 20 秒 |

来源：`../fanren_single_chapter_tts_estimate_20260616/REPORT.md`

## 引擎结论

| 引擎 | 质量/控制 | 速度 | 当前判断 |
| --- | --- | --- | --- |
| EdgeTTS | 中文稳定；情绪只能用 rate/pitch/volume 间接模拟 | 最实用，云端分钟级单章 | 用于快速预览、整书草稿、批量生产 baseline |
| CosyVoice3-0.5B | 目前本机样例里情绪表现最强，支持 instruct 和 prompt wav | 本机 CPU 很慢 | 用于关键对白、角色样例、后续精修，不适合整书本机量产 |
| Kokoro official v1.1 zh | 官方 `KPipeline` 中文比 ONNX 直跑更可信；情绪控制弱 | 快 | 可做轻量中文 baseline，但不是情绪/音色克隆主线 |
| Kokoro ONNX v1.1 zh | ONNX 推理可跑，但 G2P/Tokenizer 与官方 demo 不完全等价 | 快 | 不用作最终中文质量基线 |
| IndexTTS2 | 音色/情绪解耦能力强，适合多角色有声书 | 本机不可公平评测 | 放到远程 GPU 专项验证；未发现官方 ONNX |
| 豆包/云 API | 质量上限高，批量无本机瓶颈 | 云端 | 作为商业质量上限候选，需另评成本和接口 |

## 已保存的调研与产物

| 目录 | 内容 | 关键入口 |
| --- | --- | --- |
| `../tech_reselect_20260610` | 技术选型重审：识别侧规则+CSI，TTS 侧 Cosy/Index/云 API | `REPORT.md` |
| `../competitor_study_20260612` | 有声书生态竞品：Audiobookshelf、ebook2audiobook、Abogen、easyVoice 等 | `REPORT.md` |
| `../tts_landscape_20260612` | TTS 模型全景和速度/质量梯队 | `REPORT.md` |
| `../tts_emotion_eval_20260615` | 初版虚弱/愤怒/低语样例：Cosy、Edge、旧 Kokoro | `REPORT.md`、`playlist.html`、`manifest.json` |
| `../cosy_instruct_only_eval_20260615` | CosyVoice3 不调速、只用 instruct prompt 的情绪样例 | `REPORT.md`、`playlist.html`、`manifest.json` |
| `../indextts_bilibili_eval_20260615` | B 站 IndexTTS2 调研与本机可行性结论 | `REPORT.md`、`generate_index_samples.py` |
| `../kokoro_v11_voice_eval_20260615` | Kokoro v1.1 ONNX、voice-pack、IndexTTS2 ONNX 检查 | `REPORT.md`、`manifest.json` |
| `../kokoro_v11_official_eval_20260615` | Kokoro 官方 HF `KPipeline` 中文样例 | `REPORT.md`、`playlist.html`、`manifest.json` |
| `../tts_engine_gender_matrix_20260615` | 4 引擎 × 男女 × 3 状态播放矩阵，共 24 个样例 | `REPORT.md`、`matrix.html`、`manifest.json` |
| `../fanren_cosy_dialogue_estimate_20260615` | 《凡人》全对白 CosyVoice 生成耗时估算 | `REPORT.md`、`estimate.json` |
| `../fanren_edge_runtime_estimate_20260616` | 《凡人》整书 EdgeTTS 生成耗时估算 | `REPORT.md`、`estimate.json` |
| `../fanren_single_chapter_tts_estimate_20260616` | 《凡人》单章节 Cosy/Edge 耗时估算 | `REPORT.md`、`estimate.json` |

## 关键样例入口

- 综合播放矩阵：`../tts_engine_gender_matrix_20260615/matrix.html`
- 初版情绪播放列表：`../tts_emotion_eval_20260615/playlist.html`
- Cosy instruct-only 播放列表：`../cosy_instruct_only_eval_20260615/playlist.html`
- Kokoro 官方 v1.1 播放列表：`../kokoro_v11_official_eval_20260615/playlist.html`

## 需要保留的判断

### Kokoro

- 参考 `hexgrad/Kokoro-82M-v1.1-zh` 后，官方样例路径不是普通 `kokoro-onnx` 直跑。
- 官方路径使用 `KModel` + `KPipeline(lang_code="z")`，并带 `speed_callable`。
- 本地 ONNX v1.1 可推理，但 tokenizer/G2P 路径与官方 demo 不完全一致。
- 当前公开推理包没有音频到 voice tensor 的 few-shot 训练/导出接口，所以“用 Cosy 生成不同语气，再转换为 Kokoro 音色库”不能直接落地。

### IndexTTS2 / Bilibili

- B 站 TTS 方向对应 IndexTTS2，而不是一个轻量在线接口。
- 未发现官方 ONNX 发布路径；官方主线是 PyTorch + checkpoints。
- 本机环境缺 CUDA/MPS、git-lfs 和 checkpoints，暂未生成同文本样例。
- 适合作为远程 GPU 质量上限候选，尤其是情绪音频 prompt、8 维 emotion vector、`emo_text`。

### CosyVoice3

- 不调速、只用 instruct prompt 的样例已保存。
- 情绪控制在当前本机样例中最可用，尤其是愤怒和低语。
- 本机 CPU 推理慢：短句样例 RTF 中位数约 12.47；大批量本机生产不可接受。

### EdgeTTS

- 单条短句请求中位数约 1.53 秒。
- 项目当前并发 4 时，普通单章整章约 1.3 分钟。
- 适合先做整本草稿版，但情绪控制不是语义级，只是韵律参数模拟。

## 下一步建议

1. 实现 EdgeTTS 生产级断点续跑：片段 manifest、失败重试、只补失败片段。
2. 在 EdgeTTS 路径加入 500 到 1000 汉字切块，避免超长旁白段拖慢或失败。
3. 用 `tts_engine_gender_matrix_20260615` 作为固定 ABX 样例集，后续每接一个 TTS 后端都补齐同一矩阵。
4. 如果要追求质量上限，优先开一个 CUDA 远程 worker 跑 IndexTTS2 三状态样例，再决定是否集成。
5. 保留 CosyVoice3 作为关键对白精修/角色风格库来源，而不是当前本机整书生产后端。
