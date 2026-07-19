# Talebook 集成验收资产

本目录记录 2026-07-18/19 Talebook 私人有声书集成的真实验收结果，和历史 TTS 调研、旧版试听分开存放。

实际结果：

- EdgeTTS 可用，8 个中文音色全部生成十场景试听，共 80 段对白，见 `edge-previews.json` 和 `src/book2audio/assets/voice-previews/`。
- Qwen3TTS 请求仍被上游 `Arrearage` 拒绝，49 个 Qwen 音色不能真实预生成；没有静默切换引擎，见 `qwen-smoke.json`。
- 三部公版小说完整两章共 6 个 MP3 已在 Voicebook GitHub Pages 返回 HTTP 200，并支持 Range。
- Voicebook 自动化 38/38；Talebook 后端 626 passed、1 skipped；Talebook Nuxt E2E 34/34；Candle Reader E2E 37/37。

最终结果会写入本目录的结构化 JSON，并附录到 Talebook 的 10xdev 方案 HTML。
