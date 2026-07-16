# qwen3ttsai.com API 能力现场调研

- 调研时间：2026-07-16 18:19 +08:00
- 调研范围：仅 `qwen3ttsai.com` 当前网页和同域 API，不代表 Qwen 官方 API
- 页面：[https://qwen3ttsai.com/zh](https://qwen3ttsai.com/zh)
- 前端 bundle：`/_next/static/chunks/5519-5c66152db369e51c.js`

## 结论

1. 当前系统音色合成端点是 `POST /api/qwen3tts/generate`，前端只发送 `text`、`voice`、`mode`。没有 `prompt`、`instruct`、`style`、`emotion`、`speed` 或 `pitch` 字段，因此它不支持在每次合成时附加引导词。
2. 站点另有 `POST /api/qwen3tts/voice-design`，请求字段为 `voicePrompt`、`previewText`、`preferredName`。这里的 `voicePrompt` 是“设计一个新音色”的描述词，不是普通 `generate` 请求的逐句表演指令。
3. 站点还预留 `POST /api/qwen3tts/voice-cloning`，请求字段为 `audioData`、`audioMimeType`、`preferredName`。
4. 网页把 Voice Design 和 Voice Cloning 两个页签都禁用，并标注 `Coming Soon`。系统音色页签可见，当前 bundle 列出 49 个音色。
5. 2026-07-16 18:18 +08:00 现场请求发现，Voice Design 和普通 System Voice 生成都因站点上游账号 `Arrearage`（欠费）失败。因此“端点和字段存在”，但当前不可正常使用。

## 请求形态

```json
{
  "text": "要合成的文本，前端显示上限 1000 字符",
  "voice": "Cherry",
  "mode": "system"
}
```

```json
{
  "voicePrompt": "温暖自然的成年女声，语速适中，情绪平静",
  "previewText": "测试。",
  "preferredName": "voicebook_probe"
}
```

## 可用性证据

- `POST /api/qwen3tts/voice-design {}` 返回 HTTP 400：`声音描述不能为空`，证明服务端识别该端点和描述字段。
- 提交完整 Voice Design 请求返回 HTTP 400，错误详情为上游 `Arrearage`。
- `POST /api/qwen3tts/voice-cloning {}` 返回 HTTP 400：`音频数据不能为空`。
- 提交最小 System Voice 请求返回 HTTP 500，错误详情同为上游 `Arrearage`。

结构化现场记录见 [observations.json](./observations.json)。
