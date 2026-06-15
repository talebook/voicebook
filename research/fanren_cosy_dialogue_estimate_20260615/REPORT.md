# Fanren CosyVoice Dialogue Time Estimate

Date: 2026-06-15

## Scope

Estimate how long it would take on the current local machine to generate all quoted dialogue in `book/fanren.epub` with CosyVoice3.

This estimate counts only text inside Chinese quotation marks `“...”`; narration is excluded.

## Book Scale

| Metric | Value |
| --- | ---: |
| EPUB chapter HTML files | 2502 |
| Total Chinese chars | 6,634,162 |
| Dialogue count | 43,188 |
| Dialogue Chinese chars | 1,647,452 |
| Dialogue share by chars | 24.8% |
| Mean dialogue length | 38.1 chars |
| Median dialogue length | 25 chars |
| P90 dialogue length | 87 chars |

## Cosy Benchmarks Used

Recent local CosyVoice3 samples in this repo show:

| Metric | Value |
| --- | ---: |
| Benchmark samples | 12 |
| Mean RTF | 12.66 |
| Median RTF | 12.47 |
| Mean seconds per dialogue char | 3.44 |
| Median seconds per dialogue char | 3.51 |

These are short-dialogue CPU results, so they are pessimistic for long continuous text but realistic for a workflow that synthesizes each quoted line as a separate utterance.

## Estimate

RTF-based estimate:

| Scenario | Assumption | Wall time |
| --- | --- | ---: |
| Optimistic | 5.2 chars/sec audio, RTF 9 | 33.0 days |
| Expected | 4.8 chars/sec audio, RTF 11.5 | 45.7 days |
| Pessimistic | 4.2 chars/sec audio, RTF 14 | 63.6 days |

Observed per-char estimate:

| Scenario | Assumption | Wall time |
| --- | --- | ---: |
| Mean sample sec/char | 3.44 sec/char | 65.5 days |
| Median sample sec/char | 3.51 sec/char | 66.9 days |

## Practical Answer

For all dialogue in this EPUB, using the current local CPU CosyVoice3 path, expect roughly **45-67 days** of wall-clock generation time if every quoted line is synthesized as its own Cosy utterance.

I would use **about two months** as the planning number for this machine.

The theoretical audio duration of the dialogue itself is only around **88-109 hours**, but CosyVoice3 on this setup is much slower than realtime and short utterances have significant overhead.

## Notes

- This assumes one local worker and no GPU acceleration.
- This excludes narration. Rendering the entire book, including narration, would be several times larger.
- Batching many adjacent lines into fewer calls could reduce overhead but would weaken per-character voice/state control.
- A remote GPU worker or a faster TTS backend is the practical route for full-book production.

Detailed machine-readable output is in `estimate.json`.
