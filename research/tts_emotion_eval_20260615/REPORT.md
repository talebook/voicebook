# TTS Emotion-State Sample Evaluation

Date: 2026-06-15

## Goal

Evaluate short character dialogue in three common states:

- 虚弱: `我没事……别停下，先把药箱拿过来。`
- 愤怒: `够了！你还想瞒我到什么时候？`
- 低语: `别出声……门外有人。`

Samples are available in `playlist.html`.

## Engines

| Engine | Voice | State control |
| --- | --- | --- |
| CosyVoice3-0.5B instruct | `real_male` prompt | Instruct prompt + speed |
| Edge TTS | `zh-CN-YunxiNeural` | rate + pitch + volume |
| Kokoro ONNX | `zm_yunxi` | speed only |

## Sample Matrix

| State | CosyVoice3 | Edge TTS | Kokoro |
| --- | --- | --- | --- |
| 虚弱 | `samples/weak_cosyvoice3_real_male.wav` 7.42s | `samples/weak_edge_yunxi.mp3` 5.21s | `samples/weak_kokoro_zm_yunxi.wav` 3.99s |
| 愤怒 | `samples/angry_cosyvoice3_real_male.wav` 2.48s | `samples/angry_edge_yunxi.mp3` 3.10s | `samples/angry_kokoro_zm_yunxi.wav` 2.45s |
| 低语 | `samples/whisper_cosyvoice3_real_male.wav` 2.36s | `samples/whisper_edge_yunxi.mp3` 3.43s | `samples/whisper_kokoro_zm_yunxi.wav` 2.03s |

## Recommendation

For character dialogue with explicit states, continue with CosyVoice3 as the primary candidate. It is the only one in this set with direct instruction-level control for anger and soft voice, and it can be nudged toward weakness with slower speed and prompt wording. The tradeoff is generation latency: these samples took roughly 36s to 65s each on the local setup.

Use Edge TTS as the fast baseline. It is quick and stable once network access is available, but the emotion control is indirect. Rate, pitch, and volume can imply weak/angry/whisper, but they do not reliably change performance style.

Keep Kokoro as a fast local fallback, not as the main emotional-dialogue engine. It generated quickly after model load and sounds useful for neutral narration, but for these state labels it only exposes speed control in this script, so the state differences are comparatively shallow.

## Per-State Notes

- 虚弱: CosyVoice3 is the best direction to tune further because the longer duration and instruction path allow frailty and hesitation. Edge can simulate low energy with lower pitch and volume. Kokoro mostly becomes slower, not distinctly weak.
- 愤怒: CosyVoice3 has the strongest control surface because the prompt asks for anger directly. Edge can raise pitch/rate/volume, which gives urgency but may read as simply louder or faster. Kokoro is least differentiated.
- 低语: CosyVoice3 again has the most relevant control because of the soft-voice instruct prompt. Edge can lower volume and pitch for a whisper-like cue. Kokoro has little whisper-specific control here.

## Next Step

If we keep CosyVoice3, the next useful experiment is prompt tuning per state and per role, using 3 to 5 alternative prompts for each state rather than only one sample.
