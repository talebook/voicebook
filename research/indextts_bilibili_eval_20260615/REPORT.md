# Bilibili IndexTTS2 Emotion-State Evaluation

Date: 2026-06-15

## Scope

This note adds Bilibili's open-source TTS line to the existing emotion-state comparison in `research/tts_emotion_eval_20260615`.

The relevant Bilibili model is IndexTTS2 from the Index SpeechTeam, not a lightweight online Bilibili product API. The official repository explicitly says the only official maintained channel is `https://github.com/index-tts/index-tts`.

## Current Local Result

No custom IndexTTS2 audio was generated in this workspace.

Reason:

- The machine has no `git-lfs`, but the official setup requires cloning the repository and running `git lfs pull`.
- The workspace has no `IndexTeam/IndexTTS-2` checkpoints.
- Local PyTorch reports `cuda=False` and `mps=False`; IndexTTS2 can be initialized with `use_fp16=False`, but the official install and runtime path is designed around a full PyTorch environment and is likely impractical on this CPU-only MacBook Air workspace.

This means a fair same-text sample set requires a separate model setup step before audio comparison.

## Capability Fit

| Engine | Chinese quality expectation | Emotion control | Voice cloning | Local feasibility here |
| --- | --- | --- | --- | --- |
| CosyVoice3-0.5B | Good enough in current tests | Instruct prompt; good for angry/soft voice, weaker for explicit weak state | Prompt wav | Already runnable |
| Edge TTS | Stable, fast baseline | Indirect rate/pitch/volume only | No | Already runnable with network |
| Kokoro ONNX | Current local samples invalid for Mandarin | Speed only in our script | No few-shot audio cloning | Not suitable until retested with `misaki[zh]` |
| IndexTTS2 | Strong candidate on paper and demos | Best control surface: emotion audio prompt, 8-dim emotion vector, `use_emo_text`, explicit `emo_text` | Speaker prompt audio | Not runnable here without repo/checkpoints/GPU-class setup |

## State Mapping For Our Dialogue Test

| State | Text | Suggested IndexTTS2 control |
| --- | --- | --- |
| 虚弱 | `我没事……别停下，先把药箱拿过来。` | `emo_vector=[0, 0, 0.55, 0.15, 0, 0.45, 0, 0.1]` or `emo_text="我很虚弱，气息不足，说话断断续续。"` |
| 愤怒 | `够了！你还想瞒我到什么时候？` | `emo_vector=[0, 0.9, 0, 0, 0.15, 0, 0.1, 0]` or angry emotion prompt audio |
| 低语 | `别出声……门外有人。` | `emo_text="压低声音，小声耳语，紧张但克制。"` with lower `emo_alpha`; no dedicated whisper dimension exists in the documented vector |

## Recommendation

IndexTTS2 should stay on the shortlist and is likely the best technical fit if we can afford the runtime environment. It is specifically designed for disentangling speaker timbre and emotion, and it exposes more emotion controls than CosyVoice3.

For this project right now:

- Keep CosyVoice3 as the immediate implementation choice because it already runs locally.
- Treat IndexTTS2 as the next serious benchmark on a CUDA-capable machine or an official-compatible remote worker.
- Do not replace the current pipeline with IndexTTS2 until we generate the same three state samples and measure runtime.

## Reproduction

`generate_index_samples.py` is a small wrapper for an already-installed official IndexTTS2 checkout. It expects:

- `INDEXTTS_REPO=/path/to/index-tts`
- `INDEXTTS_CHECKPOINTS=/path/to/index-tts/checkpoints`
- `INDEXTTS_SPK_PROMPT=/path/to/index-tts/examples/voice_07.wav`

Run:

```bash
INDEXTTS_REPO=/path/to/index-tts \
INDEXTTS_CHECKPOINTS=/path/to/index-tts/checkpoints \
INDEXTTS_SPK_PROMPT=/path/to/index-tts/examples/voice_07.wav \
uv run python research/indextts_bilibili_eval_20260615/generate_index_samples.py
```

## Sources

- Official repository: https://github.com/index-tts/index-tts
- Official model: https://huggingface.co/IndexTeam/IndexTTS-2
- IndexTTS2 demo page: https://index-tts.github.io/index-tts2.github.io/
