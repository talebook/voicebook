# qwen3ttsai.com API 调研

日期：2026-07-16

## 结论

站点的系统音色合成是一个无需登录、无需 Cookie 的公开 Web 接口：

```http
POST https://qwen3ttsai.com/api/qwen3tts/generate
Content-Type: application/json
Origin: https://qwen3ttsai.com
Referer: https://qwen3ttsai.com/zh

{"text":"要合成的文本","voice":"Cherry","mode":"system"}
```

成功响应为 `audio/wav`。实测文件是 24 kHz、单声道、16-bit PCM WAV。页面输入框限制为 1000 字，voicebook 客户端会在句末标点处自动切分更长文本。

## 发现方法

1. 读取 `https://qwen3ttsai.com/zh` 当前页面和 Next.js 静态资源清单。
2. 在 chunk `5519-5c66152db369e51c.js` 中定位生成按钮的 `fetch`：路径、请求方法和 JSON 字段与用户提供的 `qwen-api-demo.py` 一致。
3. 从同一 bundle 提取 `zh-CN` 系统音色，共 27 个，见 `voice_catalog.json`。
4. 发送一条受控短文本并用 `file`/`ffprobe` 验证实际响应，原始指标见 `api_observation.json`。

## 单次探针结果

| 指标 | 结果 |
|---|---:|
| HTTP | 200 |
| 返回大小 | 73,048 bytes |
| 请求耗时 | 2.292 s |
| 音频时长 | 1.521 s |
| RTF | 1.507 |
| 格式 | PCM s16le / 24 kHz / mono |

## 其他端点

前端还包含 `/api/qwen3tts/voice-cloning` 和 `/api/qwen3tts/voice-design`，但页面将两项标为 Coming Soon。本次只接入已经可用并符合“按角色选音色”需求的 system 模式。

## 风险

- 这是网站内部 Web API，不是有版本与 SLA 的正式开放 API，路径、音色和限流策略都可能变化。
- 响应由 Cloudflare 动态回源，`cache-control: no-cache`；批量生成应控制并发并对 429/5xx 做退避重试。
- 当前无需认证不代表长期不变，因此项目仍保留 Edge 作为默认引擎，Qwen 通过 `--engine qwen` 显式启用。
