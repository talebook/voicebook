# book2audio 项目状态

## 1. 当前阶段

**Milestone**: v1.0 开发中  
**Phase**: 未开始  
**下一步**: Phase 1 讨论

---

## 2. 进度追踪

### 2.1 阶段完成情况

| Phase | 名称 | 状态 | 开始时间 | 完成时间 |
|-------|------|------|----------|----------|
| Phase 1 | 文本处理与角色分析 | Pending | - | - |
| Phase 2 | TTS语音合成 | Pending | - | - |
| Phase 3 | 音频拼接与输出 | Pending | - | - |

### 2.2 需求完成情况

| Requirement | 描述 | Phase | 状态 |
|-------------|------|-------|------|
| REQ-001 | TXT解析 | Phase 1 | Pending |
| REQ-002 | 角色识别 | Phase 1 | Pending |
| REQ-003 | 对话分类 | Phase 1 | Pending |
| REQ-004 | 画像提取 | Phase 1 | Pending |
| REQ-005 | TTS合成 | Phase 2 | Pending |
| REQ-006 | 音频拼接 | Phase 2 | Pending |
| REQ-007 | 年龄-音色 | Phase 2 | Pending |
| REQ-008 | 历史追踪 | Phase 1 | Pending |
| REQ-009 | 发言归属 | Phase 1 | Pending |
| REQ-010 | 多格式输出 | Phase 3 | Pending |
| REQ-011 | 分章节输出 | Phase 3 | Pending |

---

## 3. 决策记录

| 日期 | 决策 | 理由 | 状态 |
|------|------|------|------|
| 2026-05-09 | 使用 Qwen3-0.6B 作为 LLM | 内存≤1GB，中文优秀，已有基础 | ⚠️ 范围缩小（仅画像提取） |
| 2026-05-09 | 使用 CosyVoice 作为主要 TTS | 300M参数，原生中文，支持克隆 | ❌ 被 CosyVoice3 替代 |
| 2026-05-09 | 使用 Edge TTS 作为备选 | 免费，快速原型 | ✅ 保留（仅预览用） |
| 2026-06-10 | 说话人识别改为 规则引擎 + CSI 专用模型（chinese-roberta-wwm-ext-csi） | 程序化方案确定性高、快；0.6B LLM 逐句归属不可控。详见 research/tech_reselect_20260610/ | ✅ 决定 |
| 2026-06-10 | TTS 主线换 CosyVoice3-0.5B；预留 IndexTTS-2（远程GPU）/豆包API 高质量后端 | 真人感代际提升；Mac 无 CUDA 跑不了 IndexTTS-2 | ✅ 决定 |
| 2026-06-10 | 背景音/环境音 列为 P2 | 先跑通多角色语音主线 | ✅ 决定 |

---

## 4. 资源使用

| 资源 | 状态 | 说明 |
|------|------|------|
| 代码库 | ✅ 已初始化 | book2audio |
| 文档 | ✅ 已创建 | PROJECT.md, REQUIREMENTS.md, ROADMAP.md |
| 研究 | ✅ 已完成 | STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md |

---

## 5. 已知问题

| 问题 | 影响 | 状态 |
|------|------|------|
| 无 | - | - |

---

## 6. 下一个任务

**任务**: Phase 1 讨论和规划  
**命令**: `/gsd-discuss-phase 1`

---

*最后更新: 2026-05-09*
