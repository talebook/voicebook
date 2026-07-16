# voicebook-tool 首版能力调研摘要

日期：2026-07-16

## 调研范围

本目录为 `voicebook-tool` 首版设计单独建立，汇总仓库既有研究和当前代码事实，不重新执行历史 TTS 质量评测。

## 采用的已有证据

| 来源 | 已验证结论 | 对首版的影响 |
|---|---|---|
| `research/attribution_proto_20260610/README.md` | 规则 + 本地 CSI 融合在现有难样本金标中达到约 93%；CSI 权重约 650MB | 默认规则识别；显式下载 CSI；检测到本地模型时自动增强 |
| `research/tts_research_summary_20260616/REPORT.md` | 整书生成必须具备长文本切块、失败重试、片段缓存和断点续跑 | 缓存粒度下沉到语音片段；失败后复用已完成片段 |
| `research/competitor_study_20260612/REPORT.md` | EPUB、章节化输出、可编辑中间稿和规范元数据是成熟工具的关键能力 | 首版支持 EPUB/TXT、分章 MP3、`book.script` 和 ID3/封面 |
| `design/resources/research/20260716-qwen3ttsai-capabilities/README.md` | System Voice 请求只有 `text`、`voice`、`mode`；没有逐句引导词；站点另有未开放的 Voice Design/Cloning | `qwen3tts` 只做系统音色选择；状态控制不伪装成 API 引导词 |
| `design/20260716-qwen-title-pause-and-casting-demos.active.html` | 标题后 900ms、角色片段间 250ms、章尾 700ms 的版本已完成试听确认 | 两个引擎的最终拼接统一沿用该节奏基线 |
| `/Users/bytedance/code/txt2epub/src/txt2epub.py` | TXT 解析覆盖卷/部与章/节两级结构、同一行组合标题、序幕/尾声/番外/后记、显式 chapter/section 指令、GB18030 和缩进段落 | voicebook-tool 采用相同语义并补充锚定、长度、标点、空章和可疑章节检查，降低宽松正则误判 |

## 当前代码事实

- 现有入口是 `python -m book2audio`，只读 TXT，并用输出后缀选择 MP4、Markdown 报告或脚本。
- 已有模块覆盖中文章节切分、对白提取、规则/CSI 说话人识别、角色画像、EdgeTTS、qwen3ttsai.com、自动选声和音频边界平滑。
- 现有 Qwen 音色常量只有 27 个，而 2026-07-16 的站点 bundle 已列出 49 个；首版实现需要更新并结构化音色目录。
- 当前没有 `[project.scripts]`、EPUB 正式解析器、分章 MP3 输出、持久化 manifest 或片段级恢复机制。

## 纳入首版

1. `voicebook-tool inspect/generate/convert/models` 子命令。
2. EPUB/TXT 输入与默认整本处理，支持离散章节表达式。
3. 中文、YAML Front Matter 的 `voicebook-script` v1。
4. 自动角色识别、画像、选声、规则降级与显式 CSI 下载。
5. 默认 `qwen3tts`、可选 `edgetts`；不静默跨引擎降级。
6. 分章 MP3、可选整书 MP3、ID3 元数据和 EPUB 封面。
7. 片段级缓存、原子 manifest、失败重试、断点续跑和 `--force`。
8. 结构化 Qwen 49 音色目录，以及类型、长期地域、性别、年龄和描述的可解释评分。
9. 可分别保留男/女主角音；连续发言角色不得同音；同一角色跨章节保持同音，年龄变化除外。

## 选声补充决策（2026-07-16）

- Qwen 当前 49 个音色按 27 个普通中文、10 个中文方言、12 个海外音色分层；中文小说不能把全部音色混在一个候选池。
- 角色画像增加 `定位 / 类型 / 地域`：人类、机器人、怪兽、妖怪、灵兽、鬼魂、神明和其他非人类进入不同路由。
- 非人类角色硬路由到同声别方言池；中性/未知角色可使用全部方言池。
- 人类地域从籍贯、长期居住、群体身份和反复环境证据推断；临时旅行不改变音色，无名当地群体可以继承场景地域。
- 海外音色只有通过中文朗读可懂度测试后才能自动启用；地域与性别冲突时优先保持性别。
- 主角采用保守自动识别并允许脚本修正；最多一个男主角和一个女主角。按引擎配置的主角保留音不会分给其他角色，没有主角时保持闲置。
- 全书扫描连续发言关系形成邻接图；相邻角色不得同音。音色按规范角色 ID 全书分配一次，年龄变体可换音，情绪变化不换音。

## TXT 章节识别补充（2026-07-16）

- 参考 txt2epub 的 `RE_CHAPTER_AND_SECTIONS / RE_CHAPTERS / RE_SECTIONS` 分层思想，支持卷/部、章/节、同一行卷章组合以及序幕、尾声、番外、后记。
- 额外覆盖回、幕、集、楔子、引子、终章、大结局和受限的英文 Chapter 标题。
- 保留显式 `#@chapter:` / `#@section:` 作为最高优先级逃生口。
- 自动标题必须靠近行首、独占短行，并经过标点和长度过滤；重复标题和无正文标题不生成空音频。
- 编码依次尝试 UTF-8 BOM、UTF-8、GB18030；缩进表示新段，无缩进硬换行按句末标点合并，单字对白不得丢失。

## 暂不纳入

- PDF、MOBI/AZW3、OCR。
- SRT/ASS 字幕。
- M4B、Audiobookshelf 推送、Web UI。
- Voice Design、Voice Cloning、背景音乐和环境音。
- 旧 `book2audio` CLI 的兼容保证或清理。

完整设计见 `design/20260716-voicebook-tool.wip.html` 。
