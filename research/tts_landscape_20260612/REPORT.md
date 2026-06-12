# TTS 模型全景：性能 vs 音色（2026-06-12）

> 锚点：本机实测 edge-tts（即时）与 CosyVoice3-0.5B（Mac M系 CPU，RTF 6.4-9.5）。
> 其余数字来自公开评测，标注为文献值。

## 一、性能 vs 音色矩阵

| 模型 | 体量 | 音色/真人感 | 克隆 | 情绪控制 | RTF（本机CPU/GPU文献值） | 备注 |
|---|---|---|---|---|---|---|
| edge-tts | 云API | ★★★ 合成感明显 | ✗ | ✗(仅rate/pitch) | ~0.1（实测，即时） | 免费、快、基线 |
| Kokoro-82M | 82M | 中文★★ | ✗ | ✗ | 0.1-0.3 CPU（5月实测快） | 边缘设备级；中文弱 |
| F5-TTS | 0.33B | ★★★★ | ✓ | 弱 | CPU可跑约1-2 / GPU≈0.15 | 速度型；有 f5-tts-mlx 移植 |
| **CosyVoice3-0.5B** | 0.5B | ★★★★~★★★★½ | ✓ zero-shot | ✓ instruct指令 | **6.4 CPU（实测）** / GPU≈0.3-0.5 | 我们已接入；mlx-audio 支持 CosyVoice 系 |
| **Qwen3-TTS**（2026-01开源） | - | ★★★★½ 48kHz录音棚级（文献） | ✓ | ✓ 指令式音色设计 | **MLX 优化刚落地** | Apache-2.0；Mac 本地最值得测的新选项 |
| IndexTTS-2 | ~1.5B | ★★★★★ 公认天花板 | ✓ | ✓ 音色/情绪解耦+时长控制 | 慢（GPU实测约为CosyVoice的9倍耗时） | 需 NVIDIA 8GB+；生产默认选择（53AI报告） |
| GPT-SoVITS | - | ★★★★½（微调后克隆最像） | ✓ 需微调 | 弱 | GPU为主 | 工作流重：每角色训练 |
| Fish/OpenAudio S1 | 4B/0.5B(mini) | ★★★★½（TTS Arena前列） | ✓ | ✓ | GPU | |
| MegaTTS3 | 0.45B | ★★★★ | ✓ | 弱 | 轻量 | 字节开源；低成本商用路线 |
| VibeVoice | - | ★★★★ | ✓ | - | MLX 支持 | **原生长篇多说话人（90分钟级）**，有声书场景对口 |
| 豆包TTS/MiniMax/ElevenLabs | 云API | ★★★★★ | ✓ | ✓ | 云端，批量无瓶颈 | 按量计费；非离线 |

## 二、关键结论

1. **质量梯队**：IndexTTS-2 ≈ 云API旗舰 > Fish-S1 ≈ Qwen3-TTS ≈ GPT-SoVITS(微调) > CosyVoice3 > F5-TTS > edge-tts > Kokoro(中文)
2. **速度梯队（本机可达）**：edge-tts > Kokoro > F5-TTS-MLX ≈ Qwen3-TTS-MLX ≈ CosyVoice-MLX（待实测，预期RTF<1）≫ CosyVoice3-CPU(6.4)
3. **Mac 的破局点是 MLX**：[mlx-audio](https://github.com/Blaizzy/mlx-audio) 已支持 Kokoro/CosyVoice/Qwen3-TTS/VibeVoice——Apple GPU 加速有望把本地 RTF 压到 1 以下，"本地量产"可行性需要重新评估（此前结论基于 PyTorch-CPU）
4. **错误成本视角**：克隆质量再高，说话人归属错了照样出戏——TTS 升级与识别准确率是乘法关系
5. VibeVoice 的"90分钟长篇多说话人"定位与有声书最对口，值得单独评估

## 三、建议行动（按性价比）

1. **mlx-audio 实测**（半天）：同一段文本跑 CosyVoice-MLX / Qwen3-TTS-MLX，量 RTF 与音质——若 RTF<1，本地路线复活
2. **ABX 盲听**（已有素材）：edge vs CosyVoice3真人克隆（output/chat_cosy.mp4）vs 云API（豆包）
3. 质量上限需求再上 IndexTTS-2 远程 GPU

来源：[mlx-audio](https://github.com/Blaizzy/mlx-audio) · [Qwen3-TTS on MLX](https://mybyways.com/blog/qwen3-tts-with-mlx-audio-on-macos) · [开源TTS选型报告(53AI)](https://www.53ai.com/news/OpenSourceLLM/2026010435620.html) · [主流开源TTS对比(CSDN)](https://blog.csdn.net/shuihupo/article/details/149099684) · [五款克隆模型对比(知乎)](https://zhuanlan.zhihu.com/p/8603402649) · [MegaTTS3 vs F5实测(B站)](https://www.bilibili.com/video/BV1F5EJznEfr/)
