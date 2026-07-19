#!/usr/bin/env python3
"""为 Talebook 高级模式生成每音色十场景试听 MP3。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from book2audio.previews import PREVIEW_SCENES, assets_root
from book2audio.tool_pipeline import CloudSynthesizer
from book2audio.voice_casting import CATALOGS


SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(voice_id: str) -> str:
    value = SAFE_NAME.sub("-", voice_id).strip("-.")
    return value or hashlib.sha256(voice_id.encode()).hexdigest()[:16]


def _preview_text() -> str:
    return "\n……\n".join(f"{name}场景。{text}" for _, name, text in PREVIEW_SCENES)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration_ms(path: Path) -> int:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    return round(float(subprocess.check_output(command, text=True).strip()) * 1000)


def _encode_mp3(source: Path, output: Path, voice_id: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-b:a",
            "64k",
            "-metadata",
            f"title={voice_id} · 十场景试听",
            str(output),
        ],
        check=True,
    )


def _load_catalog(root: Path) -> dict:
    path = root / "catalog.json"
    if not path.is_file():
        return {"format": "voicebook-voice-previews", "version": 1, "voices": []}
    return json.loads(path.read_text(encoding="utf-8"))


def generate(engine: str, root: Path, force: bool) -> list[dict]:
    synth = CloudSynthesizer()
    text = _preview_text()
    records = []
    with tempfile.TemporaryDirectory(prefix="voicebook-previews-") as temporary:
        temp = Path(temporary)
        for index, profile in enumerate(CATALOGS[engine], start=1):
            relative = Path(engine) / f"{_slug(profile.voice_id)}.mp3"
            output = root / relative
            if not output.is_file() or force:
                source = temp / f"{index:03d}{'.wav' if engine == 'qwen3tts' else '.mp3'}"
                synth.synthesize(text, profile.voice_id, engine, source)
                _encode_mp3(source, output, profile.voice_id)
            record = {
                "engine": engine,
                "voice_id": profile.voice_id,
                "audio": relative.as_posix(),
                "scenes": [scene_id for scene_id, _, _ in PREVIEW_SCENES],
                "duration_ms": _duration_ms(output),
                "size_bytes": output.stat().st_size,
                "sha256": _sha256(output),
            }
            records.append(record)
            print(f"[{index}/{len(CATALOGS[engine])}] {engine} {profile.voice_id} -> {relative}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["edgetts", "qwen3tts", "all"], default="all")
    parser.add_argument("--output", type=Path, default=assets_root())
    parser.add_argument("--report", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    catalog = _load_catalog(root)
    engines = list(CATALOGS) if args.engine == "all" else [args.engine]
    retained = [item for item in catalog.get("voices", []) if item.get("engine") not in engines]
    generated = []
    failures = []
    for engine in engines:
        try:
            generated.extend(generate(engine, root, args.force))
        except Exception as exc:
            failures.append({"engine": engine, "error": str(exc)})
            if args.engine != "all":
                raise

    payload = {
        "format": "voicebook-voice-previews",
        "version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scene_count": len(PREVIEW_SCENES),
        "voices": sorted(retained + generated, key=lambda item: (item["engine"], item["voice_id"])),
    }
    (root / "catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report = {
        "generated_at": payload["generated_at"],
        "requested_engines": engines,
        "generated_voice_count": len(generated),
        "scene_count_per_voice": len(PREVIEW_SCENES),
        "failures": failures,
        "catalog": str(root / "catalog.json"),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
