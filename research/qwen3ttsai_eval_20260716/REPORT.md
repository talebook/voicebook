# Qwen3TTSAI 小说语音 Demo 与性能报告

[打开单文件 HTML 报告](qwen3ttsai-report.html)

生成时间：2026-07-16T10:54:05+08:00

## 结果摘要

- 成功率：5/5（100.0%）
- 并发：2（与 voicebook Qwen 引擎一致）
- 批次墙钟时间：12.307 s
- 合计音频时长：47.445 s
- 有效批次 RTF：0.259
- 单请求平均耗时：4.673 s
- 单请求中位耗时：4.422 s
- 最慢请求：6.640 s
- 有效文本吞吐：16.25 字/s

RTF 小于 1 表示生成速度快于最终音频播放速度；有效批次 RTF 使用批次墙钟时间除以所有音频总时长。

## Demo 明细

| Demo | 角色画像 | 自动音色 | 字数 | 请求耗时 | 音频时长 | RTF | 文件 |
|---|---|---|---:|---:|---:|---:|---|
| fanren_narrator | 旁白 | Neil | 45 | 4.422s | 8.801s | 0.502 | [01_fanren_narrator_neil.wav](samples/01_fanren_narrator_neil.wav) |
| fanren_hanli | male/青年/低沉 | Andre | 54 | 5.459s | 10.321s | 0.529 | [02_fanren_hanli_andre.wav](samples/02_fanren_hanli_andre.wav) |
| fanren_old_taoist | male/老年/苍老 | Arthur | 51 | 6.640s | 17.121s | 0.388 | [03_fanren_old_taoist_arthur.wav](samples/03_fanren_old_taoist_arthur.wav) |
| peterpan_mother | female/中年/柔和 | Serena | 27 | 3.340s | 5.521s | 0.605 | [04_peterpan_mother_serena.wav](samples/04_peterpan_mother_serena.wav) |
| peterpan_peter | male/童年/稚嫩 | Pip | 23 | 3.503s | 5.681s | 0.617 | [05_peterpan_peter_pip.wav](samples/05_peterpan_peter_pip.wav) |

所有文件均为接口原生 24 kHz / mono / 16-bit PCM WAV。样本文本来自仓库现有测试小说，详见 `manifest.json` 的原文、来源和 SHA-256。

## 角色选音说明

- 旁白固定为 Neil（阿闻），保证长篇叙述清楚稳定。
- 角色先按 male/female 与童年/少年/青年/中年/老年进入候选桶，再由低沉、沙哑、苍老、柔和、稚嫩等文本画像细化。
- 同桶多角色会依次取不同候选音色，避免主要角色撞声；配音脚本仍允许手工覆盖系统 voice id。

## voicebook 端到端验证

`novel_demo.script` 通过正式 CLI 合成了两章、四角色的多角色有声书：

[voicebook_qwen_novel_demo.mp4](voicebook_qwen_novel_demo.mp4)

另用 `tests/samples/凡人修仙之仙界篇.txt` 跑完整自动链路（说话人识别→角色画像→选声），结果为：老道 `male/老年 → Eldric Sage`，韩立 `male/青年 → Andre`。

```bash
uv --cache-dir /private/tmp/voicebook-uv-cache run python -m book2audio \
  --from-script research/qwen3ttsai_eval_20260716/novel_demo.script \
  --output research/qwen3ttsai_eval_20260716/voicebook_qwen_novel_demo.mp4 \
  --engine qwen
```

## 运行方式

```bash
uv --cache-dir /private/tmp/voicebook-uv-cache run python research/qwen3ttsai_eval_20260716/run_eval.py
```

## 限制

本报告测量的是当前网络、当前公共 Web API 和五个短小说片段，不等价于服务 SLA。站点可能动态限流；voicebook 使用并发 2，并对 429/5xx 最多尝试三次。
