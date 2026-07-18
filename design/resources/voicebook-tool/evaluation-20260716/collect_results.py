#!/usr/bin/env python3
"""收集临时生成结果、校验媒体并产出可提交的评测清单。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TEMP_ROOT = Path("/private/tmp/voicebook-tool-evaluation-20260716")
BOOKS = ("xiyouji", "rulinwaishi", "hongloumeng")


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_name,sample_rate,channels,bit_rate:format=duration,bit_rate:format_tags=title,album,artist,track",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    audio = next(stream for stream in payload["streams"] if stream.get("codec_name") == "mp3")
    format_info = payload["format"]
    return {
        "文件": path.name,
        "字节数": path.stat().st_size,
        "SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "时长秒": round(float(format_info["duration"]), 3),
        "编码": audio["codec_name"],
        "采样率": int(audio["sample_rate"]),
        "声道": int(audio["channels"]),
        "比特率": int(audio.get("bit_rate") or format_info["bit_rate"]),
        "ID3": format_info.get("tags", {}),
    }


def main() -> None:
    media = []
    for book in BOOKS:
        source = TEMP_ROOT / book
        destination = ROOT / book
        destination.mkdir(parents=True, exist_ok=True)
        mp3s = sorted(source.glob("*.mp3"))
        if len(mp3s) != 2:
            raise RuntimeError(f"{book} 应有 2 个章节 MP3，实际 {len(mp3s)}")
        copied = []
        for path in mp3s:
            target = destination / path.name
            shutil.copy2(path, target)
            copied.append(target)
            record = probe(target)
            record["书目"] = book
            media.append(record)

        manifest = json.loads((source / ".voicebook/manifest.json").read_text(encoding="utf-8"))
        manifest["脚本"] = "../book.script"
        manifest["输出"] = [f"../{path.name}" for path in copied]
        manifest_dir = destination / ".voicebook"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    report = {
        "评测": "voicebook-tool 三部公版小说完整两章试听",
        "生成时间": datetime.now(timezone.utc).isoformat(),
        "引擎": "edgetts",
        "原因": "qwen3ttsai.com 冒烟返回 Arrearage；按设计不静默回退，试听显式选择 edgetts",
        "书目数": 3,
        "章节数": len(media),
        "全部可解码": all(item["编码"] == "mp3" and item["时长秒"] > 0 for item in media),
        "媒体": media,
    }
    (ROOT / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"章节数": len(media), "总字节": sum(item["字节数"] for item in media), "总时长秒": round(sum(item["时长秒"] for item in media), 3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
