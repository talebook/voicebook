# voicebook-tool

把 EPUB/TXT 小说识别成可编辑的多角色配音脚本，并输出分章节 MP3。默认使用 qwen3ttsai.com 的 `qwen3tts`，也支持 `edgetts`。

## 文档入口

- [设计文档索引](design/)
- [voicebook-tool 首版方案](design/20260716-voicebook-tool.wip.html)
- [Qwen 标题留白与多小说 A/B 选角试听](design/20260716-qwen-title-pause-and-casting-demos.active.html#playback)
- [Qwen3TTSAI 接入与性能报告](design/20260716-qwen3ttsai-integration.active.html)

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
# 使用 EdgeTTS
voicebook-tool generate book.script -o output/ --engine edgetts

# 只生成第 1、3、8 至 12 章
voicebook-tool generate book.script -o output/ --chapters 1,3,8-12

# 同时生成全书合并 MP3
voicebook-tool generate book.script -o output/ --combine

# 忽略增量缓存，重新合成
voicebook-tool generate book.script -o output/ --force

# 显式下载约 650 MB 的可选 CSI 说话人识别模型
voicebook-tool models download csi
```

`convert` 会在输出目录保留 `book.script`。默认恢复 `.voicebook/cache/` 中已完成的片段；修改一句对白后，只重新生成受影响的片段。Qwen 失败时命令会明确报错，不会静默换成 EdgeTTS。

> 隐私提示：`qwen3tts` 和 `edgetts` 都是云端服务，生成时会把所选章节正文发送给对应第三方 TTS 服务。

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
