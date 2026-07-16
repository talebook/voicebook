# book2audio 智能有声书工具

将小说 TXT 转化为多角色有声书：识别对白/旁白与说话人，按角色匹配音色合成语音，输出带章节标记的 MP4 有声书。

## 文档入口

- [设计文档索引](design/)
- [Qwen3TTSAI 接入与性能报告](design/20260716-qwen3ttsai-integration.active.html)

## 快速开始

```bash
uv sync
uv run python -m book2audio -i book/xuanjian.txt -c 1-3 -o output/xuanjian_ch1-3.mp4
```

参数：
- `-i/--input` 小说 TXT（UTF-8）
- `-c/--chapters` 章节范围，如 `1-3` 或 `5`（默认 `1-3`）
- `-o/--output` 输出 MP4 路径
- `--keep-temp` 保留中间音频

依赖：`ffmpeg`（`brew install ffmpeg`）。

## 当前流水线

```
TXT → 章节分割 → 说话人识别(L1规则+L2 CSI模型) → 角色画像(L3规则) → 音色分配 → TTS → MP4(带章节标记)
```

常用命令：

```bash
# 多角色有声书（edge-tts，快）
uv run python -m book2audio -i book/xuanjian.txt -c 1-3 -o out.mp4 --multi-voice
# Qwen3-TTS 在线系统音色（自动按角色性别/年龄/音色描述选声）
uv run python -m book2audio -i book/xuanjian.txt -c 1 -o out_qwen.mp4 --multi-voice --engine qwen
# 识别报告（只读，人工查看）
uv run python -m book2audio -i book/xuanjian.txt -c 1-3 -o report.md
# 配音脚本（中间格式，可编辑后回灌）：先导出 → 人工改错行/角色表 → 再合成
uv run python -m book2audio -i book/xuanjian.txt -c 1-3 -o draft.script
uv run python -m book2audio --from-script draft.script -o out.mp4 --engine qwen
#   脚本里：无标签行=旁白；[角色名]=对白；[角色名@虚弱/愤怒/...]=状态(自动识别,调韵律)；
#          [角色名@老年]=年龄段切音色；同角色多年龄在角色表加 "角色名@老年" 行
```

- 说话人识别：规则层 R1-R8 + CSI RoBERTa（`models/csi-v1`，fp16 约650MB），金标 93%
- 角色画像：纯规则（性别/年龄/称呼语/辈分），(gender, age_stage) → 音色桶
- TTS：默认 `edge-tts`；可选 `qwen` 使用 `qwen3ttsai.com` 的公开 Web API（无需 Cookie，单次最多 1000 字，自动切分）。Qwen 模式从 27 个中文系统音色中按角色性别、年龄阶段和音色描述自动匹配，并在片段拼接前自动平滑 WAV 边缘以消除爆音。

## 目录结构

```
src/book2audio/     流水线源码（parser / pipeline / CLI）
book/               小说素材
design/             ACTIVE 设计文档、验证报告与本地支撑资源（GitHub Pages 索引）
research/           历次调研归档（LLM benchmark、TTS 对比、角色画像 demo、选型重审）
.planning/          项目规划（PROJECT / ROADMAP / STATE）
tests/              评测记录
```

## 路线图（摘要）

1. ✅ edge-tts 端到端基线
2. ✅ 程序化说话人识别库：规则 R1-R8 + CSI 模型融合（`research/attribution_proto_20260610/`）
3. ✅ 角色画像 → 音色自动映射（L3 纯规则）
4. 本地 TTS 只考虑约 500MB 以内模型；大模型保留在调研目录，不进入默认依赖
5. 真人参考音色库与轻量 TTS 评估；情绪→TTS 控制先基于 edge 韵律参数
6. 年龄变化音色过渡；指代消解/别名归一（识别的下一个台阶）
7. 背景音/环境音（P2）
