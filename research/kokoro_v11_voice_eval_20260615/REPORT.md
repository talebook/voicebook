# Kokoro v1.1 Mandarin and Voice-Pack Evaluation

Date: 2026-06-15

## Scope

Retest Kokoro with the Mandarin-specific v1.1 ONNX assets and the official Chinese G2P path:

- `models/kokoro-v1.1-zh.onnx`
- `models/voices-v1.1-zh.bin`
- `misaki.zh.ZHG2P(version=None)` legacy IPA output
- `kokoro_onnx.Kokoro(...).create(..., is_phonemes=True)`

This avoids the previous invalid `lang="cmn"` espeak/phonemizer path.

I also tried `misaki.zh.ZHG2P(version="1.1")`, but that emits Zhuyin-style symbols. The current `kokoro-onnx` tokenizer vocab is IPA-based, so most symbols are filtered out and the generated clips become impossibly short. The working path for the downloaded v1.1 ONNX model is therefore the legacy IPA G2P output.

## IndexTTS2 ONNX Check

I did not find an official IndexTTS2 ONNX release path. The official `index-tts/index-tts` README documents PyTorch usage via `uv`, model download from Hugging Face or ModelScope, FP16, DeepSpeed, and CUDA kernel options, but not ONNX export or ONNX Runtime inference.

So for now:

- IndexTTS2 official path: PyTorch repository + checkpoints.
- ONNX path: no official release found; any third-party export would need separate validation.

## Kokoro Voice-Pack Findings

The v1.1 zh voice file is a NumPy archive of style tensors. In this local file:

- total voices: 103
- Chinese voices: 100
- selected test voice: `zm_010`
- voice tensor shape: `(510, 1, 256)`
- dtype: `float32`

Generated samples:

- `samples/weak_kokoro_v11_zm_010.wav` - 3.73s
- `samples/angry_kokoro_v11_zm_010.wav` - 3.29s
- `samples/whisper_kokoro_v11_zm_010.wav` - 2.30s

Kokoro can load a voice tensor directly, but the public inference packages do not expose an audio-to-voice-tensor encoder. That means CosyVoice-generated wav files cannot be directly "converted" into Kokoro voice-pack entries with the current public tooling.

Practical options:

1. Average or mix existing Kokoro voice tensors. This can create nearby synthetic timbres, but it does not learn from Cosy audio.
2. Fine-tune or train Kokoro with aligned audio/text and then export style tensors. This requires a training pipeline that is not included in the public `kokoro` / `kokoro-onnx` inference packages.
3. Use CosyVoice as the expressive generator and optionally train a different model that supports speaker adaptation. This is more realistic than trying to turn Cosy output into Kokoro voice tensors.

## Recommendation

Use this v1.1 test only to decide whether Kokoro's Mandarin quality is acceptable after the correct G2P path. Do not plan the Cosy-to-Kokoro voice-pack conversion unless we find or build a Kokoro training/export pipeline.

For the original idea, the technically sound version is:

1. Generate a controlled corpus with CosyVoice: same speaker identity, multiple emotions, accurate text.
2. Use that corpus to fine-tune a TTS model that officially supports speaker adaptation.
3. If Kokoro is required, investigate full Kokoro training/export rather than inference-only voice-pack editing.

## Reproduction

Runtime packages installed into the project `.venv` with uv:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --default-index https://pypi.org/simple 'kokoro>=0.9.4' 'misaki[zh]' soundfile
```

Model files downloaded to the ignored `models/` directory:

- `kokoro-v1.1-zh.onnx` from `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.1-zh.onnx`
- `voices-v1.1-zh.bin` from `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.1-zh.bin`

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python research/kokoro_v11_voice_eval_20260615/generate_samples.py
```

## Sources

- IndexTTS2 official README: https://github.com/index-tts/index-tts
- Kokoro official README: https://github.com/hexgrad/kokoro
- Kokoro voices: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
- Kokoro ONNX v1.1 release: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1
- Misaki G2P: https://github.com/hexgrad/misaki
