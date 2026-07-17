"""voicebook-tool 的 inspect/generate/convert 主流程。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

from .attribution import Attributor
from .audio import change_pcm16_wav_tempo, smooth_pcm16_wav_edges, write_wav_silence_like
from .books import parse_chapter_selection, read_book, selected_chapters
from .casting import build_profiles
from .script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    parse_voicebook_script,
    write_voicebook_script,
)
from .tts import EdgeEngine, Qwen3TTSAIEngine, VoiceSpec, split_tts_text
from .voice_casting import DEFAULT_PROTAGONISTS, CastAssignment, assign_cast, enrich_character


DEFAULT_ENGINE = "edgetts"
AUDIO_FORMAT_VERSION = "pcm24k-mono-v1"
MP3_BITRATE = "64k"
TITLE_PAUSE_MS = 900
SEGMENT_PAUSE_MS = 250
CHAPTER_END_PAUSE_MS = 700
STATE_SPEED = {"虚弱": 0.9, "愤怒": 1.08, "冷淡": 0.96, "低语": 0.92, "悲伤": 0.9, "急切": 1.15}
AGE_STATES = {"童年", "少年", "青年", "中年", "老年", "幼体", "成年", "古老"}
SAFE_FILE_RE = re.compile(r"[^\w\-一-龥]+", re.UNICODE)
SPEAKABLE_RE = re.compile(r"[A-Za-z0-9一-龥]")


class Synthesizer(Protocol):
    def synthesize(self, text: str, voice: str, engine: str, output: Path) -> None: ...


class CloudSynthesizer:
    """现有云引擎的同步适配器；失败时保留原引擎错误，不静默切换。"""

    def synthesize(self, text: str, voice: str, engine: str, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if engine == "qwen3tts":
            try:
                asyncio.run(Qwen3TTSAIEngine().synth(text, VoiceSpec(voice), output))
            except Exception as exc:
                raise RuntimeError(f"qwen3tts 合成失败（音色 {voice}）：{exc}") from exc
            return
        if engine == "edgetts":
            try:
                asyncio.run(EdgeEngine().synth(text, VoiceSpec(voice), output))
            except Exception as exc:
                raise RuntimeError(f"edgetts 合成失败（音色 {voice}）：{exc}") from exc
            return
        raise ValueError(f"未知 TTS 引擎：{engine}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_bytes(payload)


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _sanitize_filename(title: str, fallback: str) -> str:
    cleaned = SAFE_FILE_RE.sub("-", title).strip("-_")[:80]
    return cleaned or fallback


def _segments_from_quotes(content: str, quotes) -> list[ScriptSegment]:
    by_paragraph: dict[int, list] = {}
    for quote in quotes:
        by_paragraph.setdefault(quote.para_idx, []).append(quote)
    paragraphs = [paragraph.strip() for paragraph in content.splitlines() if paragraph.strip()]
    segments: list[ScriptSegment] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        position = 0
        for quote in sorted(by_paragraph.get(paragraph_index, []), key=lambda item: item.span[0]):
            before = paragraph[position:quote.span[0]].strip()
            if before:
                segments.append(ScriptSegment("旁白", before))
            if quote.kind == "sfx":
                segments.append(ScriptSegment("音", quote.text))
            elif quote.speaker:
                tag = f"{quote.speaker}@{quote.state}" if quote.state else quote.speaker
                segments.append(ScriptSegment(tag, quote.text))
            else:
                segments.append(ScriptSegment("?", quote.text))
            position = quote.span[1]
        tail = paragraph[position:].strip()
        if tail:
            segments.append(ScriptSegment("旁白", tail))
    return segments


def _detect_protagonists(characters: list[ScriptCharacter], chapters: list[ScriptChapter]) -> None:
    counts: dict[str, int] = {}
    chapter_counts: dict[str, set[int]] = {}
    for chapter in chapters:
        for segment in chapter.segments:
            name = segment.character
            if name in {"旁白", "?", "音"}:
                continue
            counts[name] = counts.get(name, 0) + len(segment.text)
            chapter_counts.setdefault(name, set()).add(chapter.number)
    by_gender = {"男": [], "女": []}
    for character in characters:
        if character.gender in by_gender:
            by_gender[character.gender].append(character)
    for gender, group in by_gender.items():
        ranked = sorted(group, key=lambda item: (-counts.get(item.name, 0), item.name))
        if not ranked:
            continue
        top = counts.get(ranked[0].name, 0)
        second = counts.get(ranked[1].name, 0) if len(ranked) > 1 else 0
        coverage = len(chapter_counts.get(ranked[0].name, set()))
        # 保守识别：对白量、跨章覆盖、相对优势同时成立；否则留给用户编辑角色表。
        if top >= 80 and coverage >= min(2, len(chapters)) and (second == 0 or top >= second * 1.35):
            ranked[0].position = "主角"
    important = sorted(
        (character for character in characters if character.position == "配角"),
        key=lambda item: (-counts.get(item.name, 0), item.name),
    )
    for character in important[:4]:
        if counts.get(character.name, 0) >= 40:
            character.position = "重要角色"


def inspect_book(
    input_path: Path,
    output_script: Path,
    *,
    chapters: str | None = None,
    csi_model: Path | None = None,
) -> VoicebookScript:
    if output_script.suffix.lower() != ".script":
        raise ValueError("inspect 输出文件必须使用 .script 后缀")
    book = read_book(input_path)
    numbers = parse_chapter_selection(chapters, len(book.chapters))
    chosen = selected_chapters(book.chapters, numbers)
    full_text = "\n".join(chapter.content for chapter in chosen)
    model = csi_model if csi_model and csi_model.exists() else None
    attributor = Attributor(csi_model_dir=model)
    attributor.build_names(full_text)
    quotes_by_chapter = {chapter.number: attributor.attribute(chapter.content) for chapter in chosen}
    profiles = build_profiles(full_text, attributor.names)

    script_chapters = [
        ScriptChapter(chapter.number, chapter.title, _segments_from_quotes(chapter.content, quotes_by_chapter[chapter.number]), chapter.volume)
        for chapter in chosen
    ]
    used_characters = {
        segment.character
        for chapter in script_chapters for segment in chapter.segments
        if segment.character not in {"旁白", "?", "音"}
    }
    characters = [
        ScriptCharacter(
            name="旁白",
            position="旁白",
            gender="男",
            age_group="中年",
            region="中原",
            voice_description="沉稳、清晰",
            speed="x1.0",
        )
    ]
    gender_map = {"male": "男", "female": "女", "unknown": "未知"}
    for name in sorted(used_characters):
        profile = profiles.get(name)
        if profile is None:
            continue
        character = ScriptCharacter(
            name=name,
            gender=gender_map.get(profile.gender, "未知"),
            age_group=profile.age_stage,
            voice_description="、".join(profile.voice_desc),
        )
        characters.append(enrich_character(character, full_text))
    _detect_protagonists(characters[1:], script_chapters)

    output_script = output_script.expanduser().resolve()
    cover_name = ""
    if book.cover_data:
        cover_name = f"{output_script.stem}.cover{book.cover_suffix}"
        cover_path = output_script.parent / cover_name
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        cover_path.write_bytes(book.cover_data)
    script = VoicebookScript(
        title=book.title,
        description=book.description or "多角色有声书配音脚本",
        author=book.author,
        language=book.language,
        source=book.source,
        cover=cover_name,
        protagonist_voices=DEFAULT_PROTAGONISTS,
        characters=characters,
        chapters=script_chapters,
        extra_meta={"解析警告": book.warnings} if book.warnings else {},
    )
    write_voicebook_script(script, output_script)
    return script


def _require_ffmpeg() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise RuntimeError(f"缺少系统命令 {binary}，无法生成 MP3")


def _normalize_to_wav(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(temporary)],
            check=True,
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _concat_wavs(paths: list[Path], output: Path) -> None:
    if not paths:
        raise ValueError("没有可拼接音频")
    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.with_name(f".{output.name}.concat.txt")
    list_file.write_text("".join(f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in paths), encoding="utf-8")
    temporary = output.with_name(f".{output.name}.tmp.wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(temporary)],
            check=True,
        )
        temporary.replace(output)
    finally:
        list_file.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def _render_logical_segment(
    text: str,
    assignment: CastAssignment,
    engine: str,
    speed: float,
    cache_dir: Path,
    synthesizer: Synthesizer,
    force: bool,
) -> tuple[Path, str, bool]:
    fingerprint = _segment_fingerprint(text, assignment, engine, speed)
    cached = cache_dir / f"{fingerprint}.wav"
    if cached.exists() and cached.stat().st_size > 44 and not force:
        return cached, fingerprint, True
    chunks = split_tts_text(text, 800)
    temporary_dir = Path(tempfile.mkdtemp(prefix="render_", dir=cache_dir))
    chunk_wavs: list[Path] = []
    try:
        for index, chunk in enumerate(chunks):
            raw_suffix = ".wav" if engine == "qwen3tts" else ".mp3"
            raw = temporary_dir / f"{index:04d}{raw_suffix}"
            normalized = temporary_dir / f"{index:04d}.normalized.wav"
            synthesizer.synthesize(chunk, assignment.voice, engine, raw)
            _normalize_to_wav(raw, normalized)
            smooth_pcm16_wav_edges(normalized)
            chunk_wavs.append(normalized)
        combined = temporary_dir / "combined.wav"
        _concat_wavs(chunk_wavs, combined)
        change_pcm16_wav_tempo(combined, min(1.5, max(0.75, speed)))
        combined.replace(cached)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return cached, fingerprint, False


def _segment_fingerprint(text: str, assignment: CastAssignment, engine: str, speed: float) -> str:
    return _sha256_json({
        "version": AUDIO_FORMAT_VERSION,
        "text": " ".join(text.split()),
        "engine": engine,
        "voice": assignment.voice,
        "speed": round(speed, 4),
    })


def _render_with_probe(
    logical: list[tuple[ScriptSegment, CastAssignment, float]],
    engine: str,
    cache_dir: Path,
    synthesizer: Synthesizer,
    force: bool,
) -> list[tuple[Path, str, bool]]:
    """首个缺失片段串行探测服务；成功后才并发其余缺失片段。"""
    rendered: dict[int, tuple[Path, str, bool]] = {}
    missing: dict[str, list[int]] = {}
    for index, (segment, assignment, speed) in enumerate(logical):
        fingerprint = _segment_fingerprint(segment.text, assignment, engine, speed)
        cached = cache_dir / f"{fingerprint}.wav"
        if cached.exists() and cached.stat().st_size > 44 and not force:
            rendered[index] = (cached, fingerprint, True)
        else:
            missing.setdefault(fingerprint, []).append(index)
    if missing:
        probe_fingerprint = next(iter(missing))
        probe_indices = missing.pop(probe_fingerprint)
        probe = probe_indices[0]
        segment, assignment, speed = logical[probe]
        probe_result = _render_logical_segment(
            segment.text, assignment, engine, speed, cache_dir, synthesizer, force
        )
        for index in probe_indices:
            rendered[index] = probe_result
    workers = 2 if engine == "qwen3tts" else 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _render_logical_segment,
                logical[indices[0]][0].text,
                logical[indices[0]][1],
                engine,
                logical[indices[0]][2],
                cache_dir,
                synthesizer,
                force,
            ): indices
            for indices in missing.values()
        }
        for future in as_completed(futures):
            result = future.result()
            for index in futures[future]:
                rendered[index] = result
    return [rendered[index] for index in range(len(logical))]


def _cover_path(script_path: Path, script: VoicebookScript) -> Path | None:
    if not script.cover:
        return None
    cover = (script_path.parent / script.cover).resolve()
    if not cover.is_file():
        raise FileNotFoundError(f"脚本指定的封面不存在：{cover}")
    return cover


def _encode_mp3(wav: Path, output: Path, script: VoicebookScript, title: str, cover: Path | None, track: int | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav)]
    if cover:
        command.extend(("-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-disposition:v", "attached_pic"))
    command.extend((
        "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-id3v2_version", "3",
        "-metadata", f"title={title}", "-metadata", f"album={script.title}",
        "-metadata", f"artist={script.author or 'voicebook-tool'}",
    ))
    if track is not None:
        command.extend(("-metadata", f"track={track}"))
    command.append(str(output))
    subprocess.run(command, check=True)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:format=duration", "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(probe.stdout)
    codecs = {stream.get("codec_name") for stream in payload.get("streams", [])}
    duration = float(payload.get("format", {}).get("duration", 0))
    if "mp3" not in codecs or duration <= 0:
        raise RuntimeError(f"生成的 MP3 无法通过 ffprobe 校验：{output}")


def _segment_assignment(
    segment: ScriptSegment,
    character_map: dict[str, ScriptCharacter],
    base_cast: dict[str, CastAssignment],
    script: VoicebookScript,
    engine: str,
) -> tuple[CastAssignment, float]:
    name = segment.character
    if name in {"?", "音", "旁白"}:
        name = "旁白"
    character = character_map[name]
    assignment = base_cast[name]
    speed = assignment.speed
    state = segment.state
    if state in AGE_STATES:
        variant = replace(character, age_group=state)
        variant_cast = assign_cast([variant], [], engine, script.protagonist_voices.get(engine, {}))
        assignment = variant_cast[variant.name]
        speed = assignment.speed
    elif state:
        speed *= STATE_SPEED.get(state, 1.0)
    return assignment, min(1.5, max(0.75, speed))


def generate_audio(
    script_path: Path,
    output_dir: Path,
    *,
    engine: str = DEFAULT_ENGINE,
    chapters: str | None = None,
    combine: bool = False,
    force: bool = False,
    synthesizer: Synthesizer | None = None,
) -> list[Path]:
    _require_ffmpeg()
    script_path = script_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    script = parse_voicebook_script(script_path)
    available = {chapter.number for chapter in script.chapters}
    if chapters:
        numbers = parse_chapter_selection(chapters, max(available))
        missing = sorted(set(numbers) - available)
        if missing:
            raise ValueError(f"脚本中不存在所选章节：{','.join(map(str, missing))}")
    else:
        numbers = sorted(available)
    chosen = [chapter for chapter in script.chapters if chapter.number in set(numbers)]
    if not chosen:
        raise ValueError("脚本中没有选中的章节")
    character_map = script.character_map()
    if "旁白" not in character_map:
        raise ValueError("角色表必须包含旁白")
    base_cast = assign_cast(script.characters, script.chapters, engine, script.protagonist_voices.get(engine, {}))
    cache_dir = output_dir / ".voicebook" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cover = _cover_path(script_path, script)
    synth = synthesizer or CloudSynthesizer()
    output_files: list[Path] = []
    chapter_wavs: list[Path] = []
    segment_records: list[dict] = []
    manifest_path = output_dir / ".voicebook" / "manifest.json"
    manifest_base = {
        "格式": "voicebook-project",
        "版本": 1,
        "脚本": str(script_path),
        "脚本指纹": _sha256_bytes(script_path.read_bytes()),
        "引擎": engine,
        "选章": numbers,
        "选角": {name: asdict(assignment) for name, assignment in base_cast.items()},
    }
    _atomic_json(manifest_path, {**manifest_base, "状态": "生成中", "片段": [], "输出": []})

    for chapter in chosen:
        title_assignment = base_cast["旁白"]
        logical = [(ScriptSegment("旁白", chapter.title), title_assignment, title_assignment.speed)]
        logical.extend(
            (segment, *_segment_assignment(segment, character_map, base_cast, script, engine))
            for segment in chapter.segments
            if SPEAKABLE_RE.search(segment.text)
        )
        audio_parts: list[Path] = []
        rendered = _render_with_probe(logical, engine, cache_dir, synth, force)
        for index, ((segment, assignment, speed), (audio, fingerprint, cache_hit)) in enumerate(zip(logical, rendered)):
            audio_parts.append(audio)
            segment_records.append({
                "章节": chapter.number,
                "序号": index,
                "角色": segment.character,
                "音色": assignment.voice,
                "语速": speed,
                "指纹": fingerprint,
                "缓存命中": cache_hit,
            })
            _atomic_json(manifest_path, {**manifest_base, "状态": "生成中", "片段": segment_records, "输出": [str(path) for path in output_files]})
            pause_ms = TITLE_PAUSE_MS if index == 0 else SEGMENT_PAUSE_MS
            if index < len(logical) - 1:
                pause = cache_dir / f"silence-{pause_ms}ms.wav"
                if not pause.exists():
                    write_wav_silence_like(audio, pause, pause_ms)
                audio_parts.append(pause)
        final_pause = cache_dir / f"silence-{CHAPTER_END_PAUSE_MS}ms.wav"
        if not final_pause.exists():
            write_wav_silence_like(audio_parts[-1], final_pause, CHAPTER_END_PAUSE_MS)
        audio_parts.append(final_pause)
        chapter_wav = output_dir / ".voicebook" / f"chapter-{chapter.number:04d}.wav"
        _concat_wavs(audio_parts, chapter_wav)
        chapter_wavs.append(chapter_wav)
        filename = f"{chapter.number:04d}-{_sanitize_filename(chapter.title, 'chapter')}.mp3"
        chapter_mp3 = output_dir / filename
        _encode_mp3(chapter_wav, chapter_mp3, script, chapter.title, cover, chapter.number)
        output_files.append(chapter_mp3)

    if combine:
        combined_wav = output_dir / ".voicebook" / "combined.wav"
        _concat_wavs(chapter_wavs, combined_wav)
        combined_mp3 = output_dir / f"{_sanitize_filename(script.title, 'voicebook')}.mp3"
        _encode_mp3(combined_wav, combined_mp3, script, script.title, cover)
        output_files.append(combined_mp3)

    manifest = {
        **manifest_base,
        "状态": "完成",
        "片段": segment_records,
        "输出": [str(path) for path in output_files],
    }
    _atomic_json(manifest_path, manifest)
    return output_files


def convert_book(
    input_path: Path,
    output_dir: Path,
    *,
    engine: str = DEFAULT_ENGINE,
    chapters: str | None = None,
    combine: bool = False,
    force: bool = False,
    csi_model: Path | None = None,
    synthesizer: Synthesizer | None = None,
) -> list[Path]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "book.script"
    inspect_book(input_path, script_path, chapters=chapters, csi_model=csi_model)
    # inspect 已经裁剪过章节，generate 不应再次按原书总章号过滤。
    return generate_audio(script_path, output_dir, engine=engine, combine=combine, force=force, synthesizer=synthesizer)
