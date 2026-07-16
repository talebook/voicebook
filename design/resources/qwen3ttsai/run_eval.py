#!/usr/bin/env python3
"""Generate Qwen novel voice demos, benchmark data, and the ACTIVE HTML report."""

from __future__ import annotations

import hashlib
import json
import platform
import statistics
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from book2audio.casting import (
    CharacterProfile,
    QWEN_NARRATOR,
    assign_qwen_voices,
)
from book2audio.tts import QwenTTSClient


HERE = Path(__file__).resolve().parent
SAMPLE_DIR = HERE / "samples"
CONCURRENCY = 2

SAMPLES = [
    {
        "id": "fanren_narrator",
        "role": "旁白",
        "source": "tests/samples/凡人修仙之仙界篇.txt",
        "text": "石盘上的那根黑色铁针微微一颤，接着从中蹿出一道毒蛇般的黑色电芒，一下子打在了韩立的指尖上。",
        "profile": None,
    },
    {
        "id": "fanren_hanli",
        "role": "韩立",
        "source": "tests/samples/凡人修仙之仙界篇.txt",
        "text": "前辈，我们不妨开诚布公的说上一说。我恰好便是修炼时间法则，为何方才探查之时，并未发现这日晷上有什么时间之力？",
        "profile": CharacterProfile("韩立", gender="male", age_stage="青年", voice_desc=["低沉"]),
    },
    {
        "id": "fanren_old_taoist",
        "role": "老道",
        "source": "tests/samples/凡人修仙之仙界篇.txt",
        "text": "好小子，口气可真不小，一万年就想进阶中期？要道爷我说，修炼三大至尊法则，没个百万年，你别想跨过这道坎！",
        "profile": CharacterProfile("老道", gender="male", age_stage="老年", voice_desc=["苍老"]),
    },
    {
        "id": "peterpan_mother",
        "role": "妈妈",
        "source": "tests/samples/彼得·潘.txt",
        "text": "当然知道，孩子。这问题问得多傻呀，他当然是骑着山羊的。",
        "profile": CharacterProfile("妈妈", gender="female", age_stage="中年", voice_desc=["柔和"]),
    },
    {
        "id": "peterpan_peter",
        "role": "彼得·潘",
        "source": "tests/samples/彼得·潘.txt",
        "text": "我想我该回到妈妈那儿去。我估摸，也许我还能飞？",
        "profile": CharacterProfile("彼得·潘", gender="male", age_stage="童年", voice_desc=["稚嫩"]),
    },
]


def wav_metadata(audio: bytes) -> dict:
    from io import BytesIO

    with wave.open(BytesIO(audio), "rb") as wav:
        frames = wav.getnframes()
        sample_rate = wav.getframerate()
        return {
            "sample_rate_hz": sample_rate,
            "channels": wav.getnchannels(),
            "sample_width_bytes": wav.getsampwidth(),
            "frames": frames,
            "duration_seconds": frames / sample_rate,
        }


def synth_one(index: int, sample: dict, assigned: dict) -> dict:
    voice = QWEN_NARRATOR[0] if sample["profile"] is None else assigned[sample["role"]][0]
    output = SAMPLE_DIR / f"{index:02d}_{sample['id']}_{voice.lower().replace(' ', '_')}.wav"
    started = time.perf_counter()
    with QwenTTSClient() as client:
        audio = client.generate(sample["text"], voice)
    wall_seconds = time.perf_counter() - started
    output.write_bytes(audio)
    meta = wav_metadata(audio)
    return {
        "id": sample["id"],
        "role": sample["role"],
        "source": sample["source"],
        "text": sample["text"],
        "characters": len(sample["text"]),
        "profile": asdict(sample["profile"]) if sample["profile"] else {"type": "narrator"},
        "voice": voice,
        "output": str(output.relative_to(HERE)),
        "bytes": len(audio),
        "sha256": hashlib.sha256(audio).hexdigest(),
        "wall_seconds": wall_seconds,
        "rtf": wall_seconds / meta["duration_seconds"],
        "characters_per_second": len(sample["text"]) / wall_seconds,
        **meta,
    }


def _render_markdown_snapshot(manifest: dict) -> str:
    """Render a legacy snapshot in memory; 10xdev output is the HTML report."""
    results = manifest["results"]
    aggregate = manifest["aggregate"]
    lines = [
        "# Qwen3TTSAI 小说语音 Demo 与性能报告",
        "",
        f"生成时间：{manifest['generated_at']}",
        "",
        "## 结果摘要",
        "",
        f"- 成功率：{aggregate['success_count']}/{aggregate['sample_count']}（{aggregate['success_rate_percent']:.1f}%）",
        f"- 并发：{manifest['concurrency']}（与 voicebook Qwen 引擎一致）",
        f"- 批次墙钟时间：{aggregate['batch_wall_seconds']:.3f} s",
        f"- 合计音频时长：{aggregate['audio_seconds']:.3f} s",
        f"- 有效批次 RTF：{aggregate['effective_batch_rtf']:.3f}",
        f"- 单请求平均耗时：{aggregate['mean_request_seconds']:.3f} s",
        f"- 单请求中位耗时：{aggregate['median_request_seconds']:.3f} s",
        f"- 最慢请求：{aggregate['max_request_seconds']:.3f} s",
        f"- 有效文本吞吐：{aggregate['effective_characters_per_second']:.2f} 字/s",
        "",
        "RTF 小于 1 表示生成速度快于最终音频播放速度；有效批次 RTF 使用批次墙钟时间除以所有音频总时长。",
        "",
        "## Demo 明细",
        "",
        "| Demo | 角色画像 | 自动音色 | 字数 | 请求耗时 | 音频时长 | RTF | 文件 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in results:
        profile = item["profile"]
        profile_label = "旁白" if profile.get("type") == "narrator" else (
            f"{profile['gender']}/{profile['age_stage']}/{'、'.join(profile['voice_desc']) or '-'}")
        lines.append(
            f"| {item['id']} | {profile_label} | {item['voice']} | {item['characters']} | "
            f"{item['wall_seconds']:.3f}s | {item['duration_seconds']:.3f}s | {item['rtf']:.3f} | "
            f"[{Path(item['output']).name}]({item['output']}) |"
        )
    lines += [
        "",
        "所有文件均为接口原生 24 kHz / mono / 16-bit PCM WAV。样本文本来自仓库现有测试小说，详见 `manifest.json` 的原文、来源和 SHA-256。",
        "",
        "## 角色选音说明",
        "",
        "- 旁白固定为 Neil（阿闻），保证长篇叙述清楚稳定。",
        "- 角色先按 male/female 与童年/少年/青年/中年/老年进入候选桶，再由低沉、沙哑、苍老、柔和、稚嫩等文本画像细化。",
        "- 同桶多角色会依次取不同候选音色，避免主要角色撞声；配音脚本仍允许手工覆盖系统 voice id。",
        "",
        "## voicebook 端到端验证",
        "",
        "`novel_demo.script` 通过正式 CLI 合成了两章、四角色的多角色有声书：",
        "",
        "[voicebook_qwen_novel_demo.mp4](voicebook_qwen_novel_demo.mp4)",
        "",
        "另用 `tests/samples/凡人修仙之仙界篇.txt` 跑完整自动链路（说话人识别→角色画像→选声），结果为：老道 `male/老年 → Eldric Sage`，韩立 `male/青年 → Andre`。",
        "",
        "```bash",
        "uv --cache-dir /private/tmp/voicebook-uv-cache run python -m book2audio \\",
        "  --from-script design/resources/qwen3ttsai/novel_demo.script \\",
        "  --output design/resources/qwen3ttsai/voicebook_qwen_novel_demo.mp4 \\",
        "  --engine qwen",
        "```",
        "",
        "## 运行方式",
        "",
        "```bash",
        "uv --cache-dir /private/tmp/voicebook-uv-cache run python design/resources/qwen3ttsai/run_eval.py",
        "```",
        "",
        "## 限制",
        "",
        "本报告测量的是当前网络、当前公共 Web API 和五个短小说片段，不等价于服务 SLA。站点可能动态限流；voicebook 使用并发 2，并对 429/5xx 最多尝试三次。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    profiles = {sample["role"]: sample["profile"] for sample in SAMPLES if sample["profile"]}
    assigned = assign_qwen_voices(profiles)
    started = time.perf_counter()
    results = []
    errors = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {
            pool.submit(synth_one, index, sample, assigned): sample
            for index, sample in enumerate(SAMPLES, 1)
        }
        for future in as_completed(futures):
            sample = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"ok {result['id']}: {result['voice']} {result['wall_seconds']:.2f}s")
            except Exception as exc:
                errors.append({"id": sample["id"], "error": repr(exc)})
                print(f"failed {sample['id']}: {exc}")
    batch_wall = time.perf_counter() - started
    results.sort(key=lambda item: next(i for i, sample in enumerate(SAMPLES) if sample["id"] == item["id"]))
    request_times = [item["wall_seconds"] for item in results]
    audio_seconds = sum(item["duration_seconds"] for item in results)
    characters = sum(item["characters"] for item in results)
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "endpoint": QwenTTSClient.DEFAULT_BASE_URL + "/api/qwen3tts/generate",
        "concurrency": CONCURRENCY,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "aggregate": {
            "sample_count": len(SAMPLES),
            "success_count": len(results),
            "success_rate_percent": 100 * len(results) / len(SAMPLES),
            "batch_wall_seconds": batch_wall,
            "audio_seconds": audio_seconds,
            "effective_batch_rtf": batch_wall / audio_seconds if audio_seconds else None,
            "mean_request_seconds": statistics.mean(request_times) if request_times else None,
            "median_request_seconds": statistics.median(request_times) if request_times else None,
            "max_request_seconds": max(request_times) if request_times else None,
            "effective_characters_per_second": characters / batch_wall if batch_wall else None,
        },
        "results": results,
        "errors": errors,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if errors:
        raise SystemExit(f"{len(errors)} demo(s) failed")
    from build_html_report import main as build_html_report

    build_html_report()


if __name__ == "__main__":
    main()
