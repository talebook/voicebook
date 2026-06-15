# TTS Engine Gender-State Matrix

Date: 2026-06-15

## Goal

Build a single playback matrix for four TTS paths:

- Kokoro official KPipeline
- Kokoro ONNX v1.1 zh
- CosyVoice3 instruct
- Edge TTS

Each engine is rendered for male and female voices across three dialogue states:

- 虚弱
- 愤怒
- 低语

## Output

Open `matrix.html` to compare all generated samples. Each matrix cell is just an audio playback control; detailed generation parameters are in `manifest.json`.

Generated matrix size: 4 engines x 2 genders x 3 states = 24 playable samples. `manifest.json` currently has 24 samples and 0 failures.

## Voices

| Engine | Male | Female |
| --- | --- | --- |
| Kokoro official KPipeline | `zm_010` | `zf_001` |
| Kokoro ONNX v1.1 zh | `zm_010` | `zf_001` |
| CosyVoice3 instruct | `real_male` prompt wav | `real_female` prompt wav |
| Edge TTS | `zh-CN-YunxiNeural` | `zh-CN-XiaoxiaoNeural` |

## Notes

Kokoro official and Kokoro ONNX are intentionally separate rows because they are not equivalent in practice. The official path uses `KPipeline(lang_code="z")`; the ONNX path uses `kokoro_onnx` with legacy IPA G2P.

CosyVoice3 samples use instruct prompts only and do not pass an explicit `speed` argument.
