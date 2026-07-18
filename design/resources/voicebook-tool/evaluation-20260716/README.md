# voicebook-tool 多书两章试听评测

本目录用于验收 `voicebook-tool` 的真实长文本效果。书源为维基文库收录的公版中文古典小说，每部保留完整前两回，不做节选；生成时使用当前可用的 `edgetts`，默认 Qwen 服务的外部欠费状态另在方案中如实记录。

资源包括：

- `prepare_sources.py`：通过 MediaWiki API 可复现抓取文本。
- `*.txt`：三部小说的两回输入。
- `<book>/book.script`：自动识别后可编辑脚本。
- `<book>/*.mp3`：每回一份完整 MP3。
- `<book>/.voicebook/manifest.json`：选角、缓存和输出记录。
- `sources.json`：章节来源 URL 与字符数。
- `evaluation.json`：ffprobe 媒体检查和本轮执行结论。

## 复现

```bash
# 1. 下载三部公版小说前两回
uv run python prepare_sources.py

# 2. 自动识别并生成脚本
uv run voicebook-tool inspect xiyouji.txt -o xiyouji/book.script
uv run voicebook-tool inspect rulinwaishi.txt -o rulinwaishi/book.script
uv run voicebook-tool inspect hongloumeng.txt -o hongloumeng/book.script

# 3. 执行有审计记录的人工校正
uv run python review_scripts.py

# 4. 显式选择当前可用的 EdgeTTS，分别生成完整两回
uv run voicebook-tool generate xiyouji/book.script -o /private/tmp/voicebook-tool-evaluation-20260716/xiyouji --engine edgetts
uv run voicebook-tool generate rulinwaishi/book.script -o /private/tmp/voicebook-tool-evaluation-20260716/rulinwaishi --engine edgetts
uv run voicebook-tool generate hongloumeng/book.script -o /private/tmp/voicebook-tool-evaluation-20260716/hongloumeng --engine edgetts

# 5. 收集 MP3、精简 manifest 并执行 ffprobe/SHA-256 校验
uv run python collect_results.py
```

## 实际结果

- 3 部书、6 个完整章节，合计 40,657 个源文本字符。
- 合计时长 9,618.911 秒（约 160.3 分钟），总大小 76,956,262 字节（约 73.4 MiB）。
- 6 个文件均为 24 kHz、单声道、64 kbps MP3，均有正确的 title/album/artist/track ID3。
- 首次《西游记》生成暴露了“孤立标点被发送给 EdgeTTS”的问题；实现补充不可朗读片段过滤后，使用既有片段缓存成功续跑。
- Qwen 极短文本冒烟实际返回 HTTP 500 / `Arrearage`，因此本轮没有伪造 Qwen 成功，也没有静默回退；试听命令明确指定 `--engine edgetts`。

## Pages 验收

GitHub Pages 报告可用 Chromium 复验 6 个播放器和桌面/移动端布局：

```bash
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/voicebook-playwright-browsers \
  uv --cache-dir /private/tmp/voicebook-uv-cache run --with playwright \
  python design/resources/voicebook-tool/evaluation-20260716/verify_pages.py
```
