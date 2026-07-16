# Voicebook 设计文档

这里收录 Voicebook 当前有效和历史归档的内部设计、技术决策与验证报告，并作为 GitHub Pages 的 `design/` 索引。

[返回项目首页](../)

## 当前有效文档

| 状态 | 文档 | 内容 | 相关资源 |
|---|---|---|---|
| ACTIVE | [Design 文档与资源目录整理方案](./20260716-design-resources-layout.active.html) | 10xdev 文档生命周期、目录布局与资源管理约束 | — |
| ACTIVE | [Qwen 音频片段边界去爆音方案](./20260716-qwen-audio-boundary-declick.active.html) | 定位并消除多角色 MP4 在音频片段切换处的满幅瞬态 | [修复后 MP4](./resources/qwen3ttsai/voicebook_qwen_novel_demo.mp4) |
| ACTIVE | [Qwen3TTSAI 接入与性能报告](./20260716-qwen3ttsai-integration.active.html) | Web API 协议、角色自动选声、性能数据和可播放 Demo | [MP4 Demo](./resources/qwen3ttsai/voicebook_qwen_novel_demo.mp4) · [评测数据](./resources/qwen3ttsai/manifest.json) · [音色目录](./resources/qwen3ttsai/voice_catalog.json) |

## 文档状态

- `WIP`：仍在开发或验证，不应作为当前依据。
- `ACTIVE`：已经验证，代表当前有效方案。
- `SUPERSEDED`：已被新方案替代，仅用于追溯历史。

设计 HTML 直接位于 `design/`，文件名格式为 `yyyymmdd-<feature>.<status>.html`。截图、音视频、数据快照和复现脚本等支撑材料放在 `design/resources/<feature>/`，由对应设计文档使用相对路径引用。
