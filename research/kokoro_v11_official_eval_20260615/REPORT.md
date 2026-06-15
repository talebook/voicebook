# Kokoro v1.1 Official Pipeline Evaluation

Date: 2026-06-15

## Goal

Regenerate the same three dialogue-state lines with the official `hexgrad/Kokoro-82M-v1.1-zh` usage path, because the earlier ONNX test sounded less fluent than the official samples.

## Key Difference From Previous ONNX Test

The official model card points to `samples/make_zh.py`. That script uses:

- `KModel(repo_id="hexgrad/Kokoro-82M-v1.1-zh")`
- `KPipeline(lang_code="z", repo_id=..., model=model, en_callable=en_callable)`
- `voice="zf_001"` by default, with `zm_010` as an alternate
- a `speed_callable` that returns `1.1` for short text and slows longer phoneme sequences

The previous local test used `kokoro-onnx` directly. That bypasses the official pipeline behavior and is not the best comparison against the official samples.

## Generated Voices

- `zf_001`
- `zm_010`

## Files

Generated after running `generate_official_samples.py`:

- `manifest.json`
- `playlist.html`
- `samples/*.wav`

Sample durations:

| Voice | 虚弱 | 愤怒 | 低语 |
| --- | --- | --- | --- |
| `zf_001` | 3.92s | 3.23s | 2.52s |
| `zm_010` | 3.85s | 3.27s | 2.65s |

## Finding

The previous ONNX-direct test was not equivalent to the official HF demo. The official path lets `KPipeline(lang_code="z")` handle Chinese tokenization and feeds the model through `KModel`; the generated phonemes are Zhuyin-style symbols and are accepted by that path.

In contrast, the local `kokoro-onnx` package tokenizer is IPA-oriented. When I tried to feed `misaki.zh.ZHG2P(version="1.1")` output into `kokoro-onnx`, most symbols were filtered out. Switching ONNX to legacy IPA made it generate plausible-length clips, but that still does not match the official v1.1 zh pipeline.

So the better conclusion is:

- For judging `hexgrad/Kokoro-82M-v1.1-zh`, use the official `KPipeline` path.
- The earlier ONNX-direct result should not be used as the quality baseline.
- The official sample script also applies a `speed_callable`; for short text this returns `1.1`, so it is slightly faster than raw `speed=1.0`.

## Reproduction

The script uses `HF_HOME=.hf-cache` so downloaded model files stay out of the repository.

```bash
HF_HOME=.hf-cache UV_CACHE_DIR=.uv-cache \
uv run python research/kokoro_v11_official_eval_20260615/generate_official_samples.py
```

## Sources

- Model card: https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh
- Official Chinese sample script: https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/blob/main/samples/make_zh.py
