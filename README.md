# voicebook-tool

把 EPUB/TXT 小说识别成可编辑的多角色配音脚本，并输出分章节 MP3。默认使用 `edgetts`，也可显式选择 qwen3ttsai.com 的 `qwen3tts`。

## 文档入口

- [设计文档索引](design/)
- [voicebook-tool 首版方案与完整两章试听](design/20260716-voicebook-tool.active.html#full-book-demos)
- [Qwen 标题留白与多小说 A/B 选角试听](design/20260716-qwen-title-pause-and-casting-demos.active.html#playback)
- [Qwen3TTSAI 接入与性能报告](design/20260716-qwen3ttsai-integration.active.html)
- [Voicebook → Talebook 生成进度契约 v2](docs/progress-v2.md)

## 安装

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和 `ffmpeg`：

```bash
uv sync
uv run voicebook-tool --help
```

也可以安装为独立命令：

```bash
uv tool install .
voicebook-tool --version
```

发布到 PyPI 后，可直接安装：

```bash
uv tool install voicebook-tool
voicebook-tool --help
```

## 发布

本项目使用 Hatchling 构建标准的 Python sdist 与 wheel。发布前在干净的工作区执行：

```bash
uv build
uvx twine check dist/*
```

推送版本标签并在 GitHub 创建对应 Release 后，`.github/workflows/publish.yml` 会通过 PyPI Trusted Publishing 上传构件。首次发布前，需要在 PyPI 为 `voicebook-tool` 配置该仓库的 trusted publisher；仓库尚未声明许可证，请在公开发布前补充适用的 `LICENSE` 文件。

## 使用

先识别、人工检查脚本，再生成音频：

```bash
voicebook-tool inspect book.epub -o book.script
voicebook-tool generate book.script -o output/
```

或一步完成：

```bash
voicebook-tool convert book.txt -o output/
```

常用选项：

```bash
# 显式使用 Qwen3TTS
voicebook-tool generate book.script -o output/ --engine qwen3tts

# 只生成第 1、3、8 至 12 章
voicebook-tool generate book.script -o output/ --chapters 1,3,8-12

# 同时生成全书合并 MP3
voicebook-tool generate book.script -o output/ --combine

# 忽略增量缓存，重新合成
voicebook-tool generate book.script -o output/ --force

# 显式下载约 650 MB 的可选 CSI 说话人识别模型
voicebook-tool models download csi
```

`convert` 会在输出目录保留 `book.script`。默认恢复 `.voicebook/cache/` 中已完成的片段；修改一句对白后，只重新生成受影响的片段。任一引擎失败时命令都会明确报错，不会静默切换到另一引擎。

> 隐私提示：`qwen3tts` 和 `edgetts` 都是云端服务，生成时会把所选章节正文发送给对应第三方 TTS 服务。

## 单本并发与真实进度

同一章的语音片段可并发生成，结果按原章节和片段顺序合成。`--concurrency` 配置本次单本请求上限（1–32），
默认 Edge 为 1、Qwen 为 2；设为 1 可使用串行路径。Edge 多本、文本块与重试共享连接上限、5 秒启动间隔和冷却预算；其他引擎的总配额由宿主控制。
首个未缓存片段先探测服务，成功后再并发；瞬时错误默认额外重试 2 次，可用 `--max-retries 0` 关闭。

```bash
voicebook-tool generate book.script -o output/ --engine qwen3tts --concurrency 3 --resume \
  --progress-format jsonl --progress-version 2 --task-id book-job-123 \
  --cancel-file output/cancel
```

JSONL 在片段真正完成时立即上报，包含阶段、整本绝对工作量、活动请求、失败/重试/取消及更新时间。
一单位为一个章节标题或可朗读正文逻辑片段；片段比例表示工作量，不表示耗时。
音频合成、时间轴和 manifest 写入成功后才报告完成。最新事件同时原子保存到
`output/.voicebook/progress.v2.json`，human 模式也保存；每次调用默认产生新 `attempt_id`。
Edge 共享预算使用 `--edge-budget-path` 或 `VOICEBOOK_EDGE_BUDGET` 指定同一个 SQLite 文件；多 worker 必须共用文件和配置。
默认额外重试 2 次、累计退避/冷却等待预算 300 秒；有效 Retry-After 支持秒数及 HTTP 日期，等待不截短。
`rate_queued`、`rate_limit_retry`、`cooling_down` 带原因和计划请求时间；这些默认值不是官方配额或封禁时长。
创建 cancel-file 会停止提交新片段，正在执行的语音调用在返回或超时后停止后续文本块；重试前移除旧取消文件。

默认 JSONL schema 仍为 v1，新增字段和事件可被旧消费者忽略。宿主接入、尝试去重、完成条件与旧版本回退见
[进度契约](docs/progress-v2.md)。离线对照与事件演示可运行：

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python tests/concurrency_20261003/run_evaluation.py
```

评测仅使用本地模拟引擎和 ffmpeg；[报告](tests/concurrency_20261003/report.html) 展示串行、并发、限流重试、取消、失败和恢复。

## 音色试听

```bash
voicebook-tool voices --engine edgetts
voicebook-tool voices --format json --include-paths
```

安装包内预置 8 个 EdgeTTS 中文音色的试听 MP3，每个音频依次覆盖旁白、日常、喜悦、愤怒、悲伤、恐惧、低语、急切、威严和温柔 10 种场景。Qwen 目录仍会完整列出 49 个音色，但只有真实生成成功的资产才会标记为可试听；服务失败时不会用其他引擎冒充。

## book.script

脚本使用中文 YAML front matter、中文角色表和显式正文标签：

```text
---
格式: voicebook-script
版本: 1
书名: 凡人修仙传
简介: 多角色有声书配音脚本
作者: 忘语
语言: zh-CN
来源: book.epub
主角音:
  qwen3tts:
    男: Andre
    女: Serena
---

## 角色表
# 角色 | 定位 | 类型 | 性别 | 年龄段 | 地域 | 音色描述 | 语速 | 音色覆盖
旁白 | 旁白 | 人类 | 男 | 中年 | 中原 | 沉稳、清晰 | x1.0 |
韩立 | 主角 | 人类 | 男 | 青年 | 山区 | 低沉、克制 | x1.05 |
机械守卫 | 配角 | 机器人 | 中性 | 未知 | 未知 | 冷硬、短促 | x0.9 |

## 章节 0001 | 第一章 山边小村

[旁白] 二愣子睁大了双眼。
[韩立] 这里是什么地方？
[韩立@低语] 先别出声。
[?] 外面有人吗？
[音] 砰！
```

语速写成 `自动` 或 `x0.75`～`x1.5`。音色可按引擎覆盖，例如 `qwen3tts=Arthur; edgetts=zh-CN-YunyangNeural`。

## 自动选角

- Qwen 目录包含 27 个普通中文、10 个方言、12 个海外音色。
- 角色按定位、类型、性别、年龄、长期地域和声音描述匹配音色。
- 非人类角色进入方言音色池；人类有长期地域证据时优先匹配对应方言。
- 海外音色只有通过中文可懂度门禁后才能自动使用。
- 男/女主角音分别保留，不会分给其他角色；没有对应主角时保持不用。
- 连续发言的不同角色不能同音；同一角色跨章节保持同音，明确年龄变化时允许换音。

标题后留白 900ms，逻辑片段间留白 250ms，章尾留白 700ms；长文本 API 切块之间不额外加停顿。Qwen WAV 会进行边缘平滑，避免片段衔接爆音。

## 目录

```text
src/book2audio/   CLI、书籍解析、脚本、选角、TTS 与音频流水线
design/           ACTIVE/WIP/SUPERSEDED 设计文档及 GitHub Pages 索引
design/resources/ 截图、音视频、数据快照和复现脚本等支撑资源
research/         每次调研或评测的独立归档目录
tests/            单元与离线端到端测试
```
