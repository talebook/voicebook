# Chrome 是否有类似 EdgeTTS 的免费 TTS API

> 调研日期：2026-07-17  
> 范围：Chrome/Chromium Web Speech API、Chrome Extensions TTS API、Google Cloud Text-to-Speech  
> 方法：阅读 W3C、Chrome/Chromium、Google Cloud 官方资料，并直接搜索 GitHub 上的实现与源码；未下载模型、未安装依赖、未调用付费接口。

## 结论

**Chrome 没有一个可以像 `edge-tts` 那样，在 CLI 中直接提交文本并拿回 MP3 字节的免费公共 TTS 服务。**

Chrome 确实提供两类无需按次向 Chrome 付费的朗读接口：网页中的 `window.speechSynthesis` 和扩展中的 `chrome.tts`。但它们的产品定位是“让浏览器/扩展把文字读到系统音频输出”，不是“生成音频文件”：

- 返回值中没有音频字节、`Blob`、`MediaStream` 或文件句柄；
- 语音主要来自操作系统或已安装的 TTS 扩展，机器之间不能保证音色一致；
- API 运行在浏览器页面或 Chrome 扩展上下文，不是 Node/Python/服务端 API；
- 把系统输出绕到虚拟声卡再录音虽然理论上能做，但只能实时录制、不能可靠并发，还可能混入其他系统声音，不适合作为 `voicebook-tool` 的生产引擎。

如果目标是“Google 提供、可在 CLI/服务端批量生成 MP3”，对应产品是 **Google Cloud Text-to-Speech**，而不是 Chrome API。Cloud TTS 有月度免费用量，但必须启用结算，超出免费量会自动计费。因此它是“带免费额度的正式 API”，不是无限免费接口。[Google Cloud 定价](https://cloud.google.com/text-to-speech/pricing)

不过，对当前这台 MacBook 来说还有一个比 Chrome 更实际的免费本地方案：**直接调用 macOS 自带的 `say` 命令**。本机实查有 19 个中文语音条目，`say` 能直接保存 AIFF，再由项目已有的音频流水线转成 MP3。它离线、无调用费，也不需要浏览器或虚拟声卡。

直接搜索 GitHub 和本机 Chrome 组件后，发现 Chrome 确实还有一套未面向普通开发者的 **WASM TTS 内部引擎**。它从语音包生成 24 kHz PCM，但公开扩展 API 仍只负责播放。这台 Mac 上的组件清单有 217 个音色条目，却**没有普通话**，中文相关只有 5 个粤语音色。将它逆向包装成 CLI 技术上有可能，但没有稳定接口、授权和兼容保证，也不能覆盖当前中文小说的主要需求。

## 能力对比

| 方案 | 调用位置 | 语音来源 | 可控项 | 能否直接得到 MP3/音频字节 | 额度与收费 | 适合 `voicebook-tool` |
|---|---|---|---|---|---|---|
| Web Speech `speechSynthesis` | 普通网页的 `Window` | 用户代理选择的本地或远程语音 | 文本、语言、音色、音量、语速、音高 | **不能**；`speak()` 返回 `undefined`，只控制播放 | Chrome 没有单独的按次价格；远程语音可能带来延迟、带宽或成本 | **不适合** |
| Chrome Extensions `chrome.tts` | 安装了 `tts` 权限的 Chrome 扩展 | Windows SAPI 5、macOS/ChromeOS 系统语音，或其他扩展注册的引擎 | 语言、音色、音量、语速、音高、队列；SSML 为引擎尽力支持 | **不能**；`speak()` 的 Promise 不返回音频内容 | API 本身没有托管服务额度；远程扩展引擎的成本由引擎决定 | **不适合** |
| `chrome.ttsEngine` | 实现 TTS 引擎的 Chrome 扩展 | 扩展自己提供 | 扩展自定义 | 方向相反：扩展把生成的 PCM buffer 交给 Chrome 播放，不是从 Chrome 取音频 | 由扩展实现者承担 | **不是可用的现成引擎** |
| macOS `say` | macOS CLI | macOS 系统语音 | 音色、每分钟词数 | **可以**；默认直接保存 AIFF，也支持部分其他容器/编码 | 本地免费，无云额度 | **适合作为 macOS 本地引擎** |
| Google Cloud Text-to-Speech | REST/gRPC、CLI、服务端 SDK | Google Cloud 固定命名音色 | 音色及模型相关控制；传统音色支持 SSML/语速/音高等 | **可以**；响应返回 base64/二进制音频，可指定 MP3 | 有月度免费量；必须启用结算，超额自动收费 | **可以作为可选引擎** |

## 1. Web Speech API：免费朗读，不是音频生成 API

W3C Web Speech API 把 `SpeechSynthesis` 暴露在 `Window` 上。它提供的核心方法只有 `speak()`、`cancel()`、`pause()`、`resume()`、`getVoices()`；`speak()` 的返回类型是 `undefined`。`SpeechSynthesisUtterance` 可设置文本、语言、音色、音量、语速和音高，但接口中没有音频数据输出。[W3C Web Speech API 的接口定义](https://webaudio.github.io/web-speech-api/#speechsynthesis)

因此，“不能导出 MP3”不是 Chrome 页面少写了一个参数，而是当前标准接口本身就没有提供音频流或文件结果。这一点是根据标准 IDL 的直接推论。

音色也不是 Chrome 承诺的一套固定云端目录。标准中的 `localService` 只说明某个音色来自本地还是远程服务；规范明确指出远程音色可能增加延迟、带宽或成本，而默认音色如何确定取决于用户代理。[W3C `SpeechSynthesisVoice`](https://webaudio.github.io/web-speech-api/#speechsynthesisvoice)

这会带来几个批量生产问题：

- 同一段脚本在两台电脑上可能没有相同的 `voiceURI`/音色；
- 浏览器、操作系统或用户安装语音包的变化会改变可选列表；
- 只能等待实际播放结束，不能像云 API 一样快速拿回文件并做并发合成；
- 因为接口只暴露在 `Window`，Node/Python 不能把它当普通库直接调用；即使自动化启动浏览器，也仍然拿不到合成后的音频字节。

## 2. `chrome.tts`：扩展朗读 API，同样不返回音频

`chrome.tts` 是 Chrome 扩展 API，需要扩展的 `tts` 权限。Chrome 官方说明它在 Windows 使用 SAPI 5，在 macOS 和 ChromeOS 使用操作系统提供的语音合成，也允许其他扩展注册新的语音引擎。[Chrome `chrome.tts` 官方文档](https://developer.chrome.com/docs/extensions/reference/api/tts)

它比 Web Speech API 多一些扩展场景能力：

- `enqueue` 可以顺序排队；
- 可以通过 `voiceName`、`lang` 选音色和语言；
- 可控制 `rate`、`pitch`、`volume`；
- 单次 `utterance` 最大 32,768 个字符；
- 可以提交完整 SSML，但官方明确说明各引擎不一定支持全部甚至任何 SSML 标签。

但是 `chrome.tts.speak()` 仍只负责播放，Promise 会在语音真正完成之前立即 resolve，结果不包含音频。官方事件只报告开始、单词/句子边界、结束和错误等状态。[`chrome.tts.speak()` 与事件](https://developer.chrome.com/docs/extensions/reference/api/tts#method-speak)

### 为什么 `chrome.ttsEngine.onSpeakWithAudioStream` 也不能取出内置音色

`chrome.ttsEngine` 是让扩展**实现一个新的 TTS 引擎**的 API。`onSpeakWithAudioStream` 的 `sendTtsAudio` 参数要求扩展把自己生成的 `AudioBuffer` 送给 Chrome，由 Chrome 负责播放和派发事件。它不是让调用方截取系统或 Chrome 内置语音的回调。[Chrome `chrome.ttsEngine` 官方文档](https://developer.chrome.com/docs/extensions/reference/api/ttsEngine#event-onSpeakWithAudioStream)

所以实现一个扩展不能把 Chrome 现有音色“变成可下载 API”；除非扩展本身已经接入另一套能输出 PCM 的 TTS 引擎，此时真正提供合成能力的仍是那套引擎。

## 3. 在这台 Mac 上，Chrome 主要是系统语音的播放前端

Chrome 文档说明桌面平台的基础语音来自操作系统。Chromium 的 macOS 实现进一步显示，它枚举 `AVSpeechSynthesisVoice.speechVoices`，并通过 `AVSpeechSynthesizer` 播放 utterance。[Chromium macOS TTS 实现](https://chromium.googlesource.com/chromium/src/+/HEAD/content/browser/speech/tts_mac.mm)

这意味着：

- Chrome 不会在 macOS 上给 `voicebook-tool` 提供一套类似 Edge 在线音色目录的稳定合同；
- Chrome 页面看到哪些中文音色，取决于当前 macOS 已安装/可用的系统声音和扩展；
- 如果未来要支持“免费本地系统 TTS”，应直接设计独立的 macOS 系统引擎适配层，而不是让 CLI 启动 Chrome 再录扬声器。

最后一点是架构建议，不代表本次已经验证系统语音的音质或速度；本次没有做音频评测。

## 4. 本机 macOS `say`：更实际的本地免费后端

本机执行 `say -v '?'` 后，按 `zh_CN`、`zh_TW`、`zh_HK` 统计到 **19 个中文语音条目**：

```text
Eddy     zh_CN / zh_TW
Flo      zh_CN / zh_TW
Grandma  zh_CN / zh_TW
Grandpa  zh_CN / zh_TW
Reed     zh_CN / zh_TW
Rocko    zh_CN / zh_TW
Sandy    zh_CN / zh_TW
Shelley  zh_CN / zh_TW
Meijia   zh_TW
Sinji    zh_HK
Tingting zh_CN
```

这是 19 个“音色 + 地区”条目，不等于 19 个完全不同的声线；同名的大陆/台湾版本仍需实际试听后才能判断角色区分度。

本机 `man say` 给出的官方系统手册说明：

- `say` 使用系统 Speech Synthesis Manager；
- `-v voice` 选择语音；
- `-r rate` 设置每分钟词数；
- `-o outfile` 把语音保存到文件，AIFF 是默认且应被大多数音色支持的格式；
- 它还支持 AIFF、CAF、M4A、WAVE 等容器，但具体编码取决于音色和系统支持。

因此可落地的流水线是：

```text
book.script 分段 → say -v <voice> -r <wpm> -o segment.aiff → ffmpeg 转 MP3 → 拼接章节
```

相较 Chrome 方案，它有三个直接优势：真正输出文件、能从 CLI 调用、无需运行浏览器。限制也很明确：仅适用于 macOS，音色与系统版本/本机安装状态有关，`book.script` 的 `x0.9` 需要适配为一个经过试听校准的 WPM 值。

本次只枚举音色并核对系统手册，没有合成样音，也没有下载额外语音包；音质、真实速度、并发安全性应另建评测后再决定是否进入正式 provider 列表。

## 5. Google Cloud TTS：真正能生成 MP3，但不是无限免费

Google Cloud TTS 的 REST/SDK 会返回 base64 或二进制 `audioContent`，请求可以明确指定 `MP3`，官方示例也直接把响应保存为 `.mp3` 文件。这符合 `voicebook-tool` 的 CLI 与分章节音频流水线。[Google Cloud 创建音频文件](https://docs.cloud.google.com/text-to-speech/docs/create-audio)

### 2026-07-17 官方价格

Google 按每月提交的字符数计费；空格、换行和绝大多数 SSML 标签也计入字符数。必须启用 billing，超过免费字符数会自动收费。[Google Cloud TTS 定价说明](https://cloud.google.com/text-to-speech/pricing)

| 音色/模型 | 每月免费量 | 超额价格 |
|---|---:|---:|
| Standard | 400 万字符 | 4 美元 / 100 万字符 |
| WaveNet | 400 万字符 | 4 美元 / 100 万字符 |
| Neural2 | 100 万字符 | 16 美元 / 100 万字符 |
| Polyglot（Preview） | 100 万字符 | 16 美元 / 100 万字符 |
| Chirp 3: HD | 100 万字符 | 30 美元 / 100 万字符 |
| Studio | 100 万字符 | 160 美元 / 100 万字符 |
| Gemini TTS | 无免费量 | 按文本 token 与音频 token 计费 |

以一本约 100 万字符的中文小说估算：Standard/WaveNet 的月免费量大约能覆盖 4 本，Chirp 3/Neural2 大约覆盖 1 本。实际还要把标点、换行、SSML 和重试重复提交计入，所以不能把书籍正文净字符数直接当最终账单数。

### 限流和切片

普通 Cloud TTS 请求的正文上限是 5,000 **字节**，不能申请提高；普通音色默认限额为每项目每分钟 1,000 次请求，Neural2 也是每分钟 1,000 次，Chirp 3 是每分钟 200 次。[Cloud TTS Quotas & limits](https://docs.cloud.google.com/text-to-speech/quotas)

对 UTF-8 中文而言，5,000 字节通常只有约 1,600 个汉字左右，因此必须继续使用 `voicebook-tool` 的分段、重试与音频拼接机制，不能把整章文本一次提交。

### 中文音色数量与角色分配

官方当前列出的中国大陆普通话音色包括：

- Standard A–D：4 个；
- WaveNet A–D：4 个；
- Chirp 3: HD：30 个命名音色，男女均有。

参见 [Cloud TTS 普通话音色列表](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types#list_of_all_supported_languages)。

对于多角色小说，Standard/WaveNet 只有 4 个普通话音色，角色区分能力明显弱于 EdgeTTS 或拥有更多音色的 Qwen 服务。Chirp 3 的 30 个音色更适合多角色候选池，但官方说明 Chirp 3 不支持 SSML 输入，也不支持 speaking rate 和 pitch 参数；这会与 `book.script` 中按角色设置 `x0.9` 等语速的需求冲突。[Cloud TTS 音色类型说明](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types#chirp_3_hd_voices)

## 6. GitHub 直接搜索结果

### Chrome 当前的 `WasmTtsEngine`

GitHub 代码搜索找到 Chromium 官方的 [`wasm_tts_engine_component_installer.cc`](https://github.com/chromium/chromium/blob/main/chrome/browser/component_updater/wasm_tts_engine_component_installer.cc)。本机 Chrome 也已自动安装：

```text
~/Library/Application Support/Google/Chrome/WasmTtsEngine/20260709.1
engine size: about 22 MiB
bindings_main.wasm: about 22 MiB
voice entries in voices.json: 217
```

本地 `voices.json` 列出 66 个语言/模型包条目、合计 217 个 speaker。语音包从 `dl.google.com/android/tts/v26/` 或 `redirector.gvt1.com` 按需下载，单包通常约 9–18 MB；本次没有下载任何语音包。

关键的中文覆盖是：

- 无 `zh-CN` / `cmn-CN` 普通话包；
- 有 `yue-HK` 粤语包，包含 3 个女声和 2 个男声；
- 清单还覆盖英语、日语、韩语和多种欧洲/亚洲语言，但不能替代普通话旁白。

本机组件源码还显示，WASM 内部通过 `_GoogleTtsInitBuffered` / `_GoogleTtsReadBuffered` 取回 24 kHz PCM，转成 `Float32Array` 后送给 `AudioWorklet`。这证明引擎内部确实有原始音频，但组件通过 `chrome.ttsEngine.onSpeak` 和 offscreen document 把它直接播放，没有向 `chrome.tts` 调用方返回这些 buffer。

所以可能的实验路径是从 Chrome 组件中抽出 WASM 绑定，自己包装 PCM 输出。但这是对内部实现的依赖，版本可随 Chrome 更新而变，语音包与 WASM 的独立分发/使用边界也未在公开 API 文档中授权。不适合作为 `voicebook-tool` 的默认或公开后端。

### 其他候选项目

| GitHub 项目 | 实际做法 | 维护/许可状态 | 对本项目的判断 |
|---|---|---|---|
| [`guest271314/SpeechSynthesisRecorder`](https://github.com/guest271314/SpeechSynthesisRecorder) | 通过 `getUserMedia()` 选择 PulseAudio 的“Monitor of Built-in Audio”，用 `MediaRecorder` 录下 `speechSynthesis` 播放 | 86 stars，2025 年还有提交，但仓库无 license | 是系统回录，不是直接获得 TTS buffer；在 macOS 上还需虚拟音频设备，只能实时生成，不适合 |
| [`biemster/gtts`](https://github.com/biemster/gtts) | 直接调用 ChromeOS/Android 旧版 `libchrometts.so` 和 `.zvoice` 包，从 `GoogleTtsReadBuffered` 写出 raw PCM | 37 stars，最后提交 2021，无 license | 证明技术上可取 PCM，但需自行寻找原生库/语音包，不是 Mac 现成方案，不建议集成 |
| [`pndurette/gTTS`](https://github.com/pndurette/gTTS) | 调用 Google Translate 未公开的网络 TTS，直接返回 MP3 | 2.6k stars、MIT、2026 年活跃 | 能快速接入 Python，但官方 README 明示警告 upstream 可随时破坏；只有 `lang`/`tld` 和 `slow` 开关，没有多音色、pitch 或 `x0.9` 连续语速控制 |
| [`nateshmbhat/pyttsx3`](https://github.com/nateshmbhat/pyttsx3) | Python 包装 AVSpeech/SAPI5/eSpeak 等系统引擎，支持 `save_to_file` | 2.5k stars、MPL-2.0、2026 年活跃 | 比 Chrome 包装更合理；但 macOS AVSpeech 驱动仍标记为 experimental，对本机直接调 `say` 更简单 |
| [`Marak/say.js`](https://github.com/Marak/say.js) | Node.js 包装 macOS `say`，`export()` 直接落 WAV | 1.5k stars、MIT，最后提交 2023 | 证明系统 TTS 落盘路线成熟；本项目是 Python，无需多加 Node 包装层 |
| [`hkdb/offline-tts`](https://github.com/hkdb/offline-tts) | Chrome 扩展内用 ONNX Runtime Web 运行 Supertonic | 8 stars、Apache-2.0 | 真正离线，但只有英语/韩语 4 音色，不符合中文小说 |

GitHub 结果里最接近“免费且直接 MP3”的是 `gTTS`，但它不是 Chrome 公共 API，而是 Google Translate 未公开端点的客户端。它适合做一次快速可抛弃评测，不适合承担多角色有声书的稳定主引擎。

## 对 `voicebook-tool` 的建议

### 不建议增加 `chrome` 引擎

Chrome 的两套接口适合网页辅助朗读和扩展无障碍功能，但不具备本项目最关键的“返回可保存、可拼接、可并发处理的音频内容”。为了获取文件而引入浏览器自动化、虚拟声卡和实时录音，会增加平台依赖、时长和不确定性，收益很低。

### 优先评测 macOS `say` 本地引擎

如果当前目标是再增加一个真正免费、能落盘的引擎，`say` 比 Chrome 更值得先做小规模评测。建议用本机 19 个中文条目各生成同一组旁白、青年男女、老人和怪物台词，测音色可区分度、实时率、AIFF 到 MP3 的衔接噪声，以及连续片段间停顿。它应作为 macOS 专属 provider，不应冒充跨平台方案。

### 可以考虑增加 `googlecloud` 可选引擎

如果需要一套有正式文档、稳定 REST API、直接 MP3 输出和明确配额的 Google 方案，可以把 Google Cloud TTS 作为后续可选引擎：

1. 默认优先试 WaveNet：每月 400 万字符免费，普通话有 4 个固定音色，也支持项目已有的语速/SSML控制；
2. 多角色试听可试 Chirp 3：音色池更大，但每月只有 100 万字符免费，而且无法按 `book.script` 调语速；
3. 启用前必须让用户显式配置 Google Cloud 项目、凭证和费用保护，不应把“有免费额度”包装成“永久免费”；
4. 在生成前按正文、标点、换行、SSML 和预计重试计算字符预算，并提供硬性预算上限，避免自动超额计费。

综合判断：**Chrome API 不值得集成；短期最值得评测的是本机 macOS `say`，因为它免费且能直接落盘；Google Cloud TTS 则适合作为正式、带免费额度的云端备选 provider，但不能宣传成无限免费。**

## 官方资料

- [W3C Web Speech API](https://webaudio.github.io/web-speech-api/)
- [Chrome Extensions `chrome.tts`](https://developer.chrome.com/docs/extensions/reference/api/tts)
- [Chrome Extensions `chrome.ttsEngine`](https://developer.chrome.com/docs/extensions/reference/api/ttsEngine)
- [Chromium macOS TTS 实现](https://chromium.googlesource.com/chromium/src/+/HEAD/content/browser/speech/tts_mac.mm)
- [Chromium WASM TTS 组件安装器](https://github.com/chromium/chromium/blob/main/chrome/browser/component_updater/wasm_tts_engine_component_installer.cc)
- [SpeechSynthesisRecorder](https://github.com/guest271314/SpeechSynthesisRecorder)
- [ChromeOS `libchrometts` CLI 概念验证](https://github.com/biemster/gtts)
- [gTTS](https://github.com/pndurette/gTTS)
- [pyttsx3](https://github.com/nateshmbhat/pyttsx3)
- [say.js](https://github.com/Marak/say.js)
- [Google Cloud TTS 创建 MP3](https://docs.cloud.google.com/text-to-speech/docs/create-audio)
- [Google Cloud TTS 定价](https://cloud.google.com/text-to-speech/pricing)
- [Google Cloud TTS 限额](https://docs.cloud.google.com/text-to-speech/quotas)
- [Google Cloud TTS 音色列表](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types)
