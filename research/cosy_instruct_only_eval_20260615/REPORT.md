# CosyVoice3 Instruct-Only Emotion Evaluation

Date: 2026-06-15

## Goal

Regenerate the three character-state dialogue samples with CosyVoice3 using only `inference_instruct2` prompts. This run does not pass a `speed` argument; CosyVoice3 uses its default `speed=1.0`.

## States

| State | Text | Instruct prompt |
| --- | --- | --- |
| 虚弱 | `我没事……别停下，先把药箱拿过来。` | `请用虚弱、气息不足、带一点停顿的状态说这句话。` |
| 愤怒 | `够了！你还想瞒我到什么时候？` | `请用愤怒、压抑不住情绪的语气说这句话。` |
| 低语 | `别出声……门外有人。` | `请压低声音，用低声耳语、紧张克制的语气说这句话。` |

## Files

Generated files:

- `samples/weak_cosyvoice3_instruct_only.wav` - 3.64s
- `samples/angry_cosyvoice3_instruct_only.wav` - 3.40s
- `samples/whisper_cosyvoice3_instruct_only.wav` - 1.40s
- `manifest.json`
- `playlist.html`

## Notes

The previous CosyVoice3 run in `../tts_emotion_eval_20260615` mixed instruct prompts with explicit `speed` values. This folder isolates prompt-only behavior so we can judge how much emotion control comes from the instruction itself.

Compared with the previous speed-adjusted run, the weak sample is much shorter (`3.64s` here vs `7.42s` before). This is expected: the earlier sample was strongly shaped by `speed=0.78`, while this run leaves timing to the model and prompt.
