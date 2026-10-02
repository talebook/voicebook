"""voicebook-tool 的 inspect/generate/convert 主流程。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event
from typing import Protocol

from .attribution import Attributor
from .audio import (
    change_pcm16_wav_tempo,
    smooth_pcm16_wav_edges,
    write_wav_silence_like,
)
from .books import parse_chapter_selection, read_book, selected_chapters
from .casting import build_profiles
from .edge_budget import EdgeBudget
from .machine import GenerationCancelled, ProgressEmitter, check_cancelled
from .provider_errors import error_info, safe_error
from .script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    parse_voicebook_script,
    write_voicebook_script,
)
from .script_quality import prepare_new_script
from .tts import EdgeEngine, Qwen3TTSAIEngine, VoiceSpec, split_tts_text
from .voice_casting import (
    DEFAULT_PROTAGONISTS,
    CastAssignment,
    assign_cast,
    enrich_character,
)
from .work import WorkProgress, render_bounded, retry_details

DEFAULT_ENGINE = "edgetts"
AUDIO_FORMAT_VERSION = "pcm24k-mono-v1"
MP3_BITRATE = "64k"
TITLE_PAUSE_MS = 900
SEGMENT_PAUSE_MS = 250
CHAPTER_END_PAUSE_MS = 700
MEDIA_HEARTBEAT_SECONDS = 1.0
STATE_SPEED = {
    "虚弱": 0.9,
    "愤怒": 1.08,
    "冷淡": 0.96,
    "低语": 0.92,
    "悲伤": 0.9,
    "急切": 1.15,
}
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
                asyncio.run(Qwen3TTSAIEngine(max_attempts=1).synth(text, VoiceSpec(voice), output))
            except Exception as exc:
                raise RuntimeError(safe_error(exc)) from exc
            return
        if engine == "edgetts":
            try:
                asyncio.run(EdgeEngine(max_attempts=1, single_request=True).synth(text, VoiceSpec(voice), output))
            except Exception as exc:
                raise RuntimeError(safe_error(exc)) from exc
            return
        raise ValueError(f"未知 TTS 引擎：{engine}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return round(source.getnframes() * 1000 / source.getframerate())


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


def _locator_for_range(base: dict[str, object], paragraph: str, start: int, end: int) -> dict[str, object]:
    while start < end and paragraph[start].isspace():
        start += 1
    while end > start and paragraph[end - 1].isspace():
        end -= 1
    locator = dict(base)
    locator.update(
        {
            "start_char": start,
            "end_char": end,
            "text_sha256": _sha256_bytes(paragraph[start:end].encode("utf-8")),
        }
    )
    return locator


def _segments_from_quotes(chapter, quotes) -> list[ScriptSegment]:
    content = chapter.content
    by_paragraph: dict[int, list] = {}
    for quote in quotes:
        by_paragraph.setdefault(quote.para_idx, []).append(quote)
    paragraphs = [paragraph.strip() for paragraph in content.splitlines() if paragraph.strip()]
    source_paragraphs = chapter.paragraphs or []
    segments: list[ScriptSegment] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        base_locator = (
            source_paragraphs[paragraph_index].locator
            if paragraph_index < len(source_paragraphs)
            else {"type": "text-segment", "paragraph_index": paragraph_index}
        )
        position = 0
        for quote in sorted(by_paragraph.get(paragraph_index, []), key=lambda item: item.span[0]):
            before = paragraph[position:quote.span[0]].strip()
            if before:
                segments.append(
                    ScriptSegment(
                        "旁白",
                        before,
                        _locator_for_range(base_locator, paragraph, position, quote.span[0]),
                    )
                )
            if quote.kind == "sfx":
                tag = "音"
            elif quote.speaker:
                tag = f"{quote.speaker}@{quote.state}" if quote.state else quote.speaker
            else:
                tag = "?"
            segments.append(
                ScriptSegment(
                    tag,
                    quote.text,
                    _locator_for_range(base_locator, paragraph, quote.span[0], quote.span[1]),
                )
            )
            position = quote.span[1]
        tail = paragraph[position:].strip()
        if tail:
            segments.append(
                ScriptSegment(
                    "旁白",
                    tail,
                    _locator_for_range(base_locator, paragraph, position, len(paragraph)),
                )
            )
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
        ScriptChapter(
            chapter.number,
            chapter.title,
            _segments_from_quotes(chapter, quotes_by_chapter[chapter.number]),
            chapter.volume,
            chapter.source_key,
        )
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
    prepare_new_script(script, book.quality_report)
    write_voicebook_script(script, output_script)
    return script


def _require_ffmpeg() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise RuntimeError(f"缺少系统命令 {binary}，无法生成 MP3")


def _run_media(
    command: list[str],
    *,
    work: WorkProgress | None = None,
    cancel_file: Path | None = None,
    capture_output: bool = False,
    stop: Event | None = None,
):
    """Service control and all active leases while waiting for our media child."""
    poll_seconds = min(0.1, MEDIA_HEARTBEAT_SECONDS)
    if work and work.budget:
        poll_seconds = min(poll_seconds, work.budget.renew_interval)
    next_heartbeat = time.monotonic() + MEDIA_HEARTBEAT_SECONDS

    def service(*, check_control=True):
        nonlocal next_heartbeat
        if work:
            work.renew_requests()
        if check_control:
            try:
                check_cancelled(cancel_file)
                if stop and stop.is_set():
                    raise GenerationCancelled("已停止音频处理")
            except GenerationCancelled:
                if work and work.status != "cancelling":
                    work.status = "cancelling"
                    work.emit("cancel_requested", retryable=True)
                raise
        if work and time.monotonic() >= next_heartbeat:
            work.emit("heartbeat")
            next_heartbeat = time.monotonic() + MEDIA_HEARTBEAT_SECONDS

    service()
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
    ) as process:
        try:
            while True:
                service()
                try:
                    stdout, stderr = process.communicate(timeout=poll_seconds)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            if process.poll() is None:
                process.terminate()
            deadline = time.monotonic() + 5
            while True:
                service(check_control=False)
                try:
                    process.communicate(timeout=poll_seconds)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        process.kill()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
        service()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _normalize_to_wav(
    source: Path, destination: Path, *, work: WorkProgress | None = None,
    cancel_file: Path | None = None, stop: Event | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp.wav")
    try:
        _run_media(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(temporary)],
            work=work, cancel_file=cancel_file, stop=stop,
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _concat_wavs(
    paths: list[Path],
    output: Path,
    *,
    work: WorkProgress | None = None,
    cancel_file: Path | None = None,
    stop: Event | None = None,
) -> None:
    if not paths:
        raise ValueError("没有可拼接音频")
    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.with_name(f".{output.name}.concat.txt")
    list_file.write_text(
        "".join(
            f"file '{str(path.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for path in paths
        ),
        encoding="utf-8",
    )
    temporary = output.with_name(f".{output.name}.tmp.wav")
    try:
        _run_media(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            work=work,
            cancel_file=cancel_file,
            stop=stop,
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
    cancel_file: Path | None = None,
    stop: Event | None = None,
) -> tuple[Path, str, bool]:
    def check_control():
        check_cancelled(cancel_file)
        if stop and stop.is_set():
            raise GenerationCancelled("已停止提交生成请求")

    check_control()
    fingerprint = _segment_fingerprint(text, assignment, engine, speed)
    cached = cache_dir / f"{fingerprint}.wav"
    if cached.exists() and cached.stat().st_size > 44 and not force:
        return cached, fingerprint, True
    chunks = split_tts_text(text, 800)
    temporary_dir = Path(tempfile.mkdtemp(prefix="render_", dir=cache_dir))
    chunk_wavs: list[Path] = []
    try:
        for index, chunk in enumerate(chunks):
            check_control()
            raw_suffix = ".wav" if engine == "qwen3tts" else ".mp3"
            raw = temporary_dir / f"{index:04d}{raw_suffix}"
            normalized = temporary_dir / f"{index:04d}.normalized.wav"
            synthesizer.synthesize(chunk, assignment.voice, engine, raw)
            check_control()
            _normalize_to_wav(raw, normalized, cancel_file=cancel_file, stop=stop)
            smooth_pcm16_wav_edges(normalized)
            chunk_wavs.append(normalized)
        combined = temporary_dir / "combined.wav"
        _concat_wavs(chunk_wavs, combined, cancel_file=cancel_file, stop=stop)
        change_pcm16_wav_tempo(
            combined, min(1.5, max(0.75, speed)),
            run_command=lambda command: _run_media(command, cancel_file=cancel_file, stop=stop),
        )
        check_control()
        combined.replace(cached)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return cached, fingerprint, False


def _render_steps(text, assignment, engine, speed, cache_dir, synthesizer, force,
                  cancel_file, stop, work):
    """Yield network-only operations; queueing and local processing stay on the coordinator."""
    def check_control():
        check_cancelled(cancel_file)
        if stop.is_set():
            raise GenerationCancelled("已停止提交生成请求")

    check_control()
    fingerprint = _segment_fingerprint(text, assignment, engine, speed)
    cached = cache_dir / f"{fingerprint}.wav"
    if cached.exists() and cached.stat().st_size > 44 and not force:
        return cached, fingerprint, True
    temporary_dir = Path(tempfile.mkdtemp(prefix="render_", dir=cache_dir))
    chunks = split_tts_text(text, 600 if engine == "edgetts" else 800)
    chunk_wavs = []
    try:
        for index, chunk in enumerate(chunks):
            check_control()
            raw = temporary_dir / f"{index:04d}.mp3"
            normalized = temporary_dir / f"{index:04d}.normalized.wav"

            def request(chunk=chunk, raw=raw):
                check_control()
                synthesizer.synthesize(chunk, assignment.voice, engine, raw)

            yield request
            check_control()
            _normalize_to_wav(raw, normalized, work=work, cancel_file=cancel_file, stop=stop)
            smooth_pcm16_wav_edges(normalized)
            chunk_wavs.append(normalized)
        combined = temporary_dir / "combined.wav"
        _concat_wavs(chunk_wavs, combined, work=work, cancel_file=cancel_file, stop=stop)
        change_pcm16_wav_tempo(
            combined, min(1.5, max(0.75, speed)),
            run_command=lambda command: _run_media(command, work=work, cancel_file=cancel_file, stop=stop),
        )
        check_control()
        combined.replace(cached)
        return cached, fingerprint, False
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


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
    *,
    work: WorkProgress,
    chapter_number: int,
    cancel_file: Path | None,
    max_retries: int,
    retry_backoff: float,
    edge_budget: EdgeBudget | None,
    max_wait_seconds: float,
) -> list[tuple[Path, str, bool]]:
    rendered: dict[int, tuple[Path, str, bool]] = {}
    missing: dict[str, list[int]] = {}
    unit_ids = [_unit_id(chapter_number, index) for index in range(len(logical))]

    def completed(index, result):
        work.complete(
            unit_ids[index],
            chapter_number=chapter_number,
            segment_index=index - 1,
            result=result,
        )

    for index, (segment, assignment, speed) in enumerate(logical):
        check_cancelled(cancel_file)
        fingerprint = _segment_fingerprint(segment.text, assignment, engine, speed)
        cached = cache_dir / f"{fingerprint}.wav"
        if cached.exists() and cached.stat().st_size > 44 and not force:
            rendered[index] = (cached, fingerprint, True)
            completed(index, rendered[index])
        else:
            missing.setdefault(fingerprint, []).append(index)

    def render(index, stop):
        segment, assignment, speed = logical[index]
        return _render_logical_segment(
            segment.text,
            assignment,
            engine,
            speed,
            cache_dir,
            synthesizer,
            force,
            cancel_file,
            stop,
        )

    def steps(index, stop):
        segment, assignment, speed = logical[index]
        return _render_steps(segment.text, assignment, engine, speed, cache_dir,
                             synthesizer, force, cancel_file, stop, work)

    rendered.update(
        render_bounded(
            list(missing.items()),
            render,
            work,
            unit_ids,
            completed,
            cancel_file,
            max_retries,
            retry_backoff,
            budget=edge_budget,
            steps=steps if edge_budget else None,
            max_wait_seconds=max_wait_seconds,
        )
    )
    return [rendered[index] for index in range(len(logical))]


def _unit_id(chapter_number: int, index: int) -> str:
    suffix = "title" if index == 0 else f"segment-{index - 1}"
    return f"chapter-{chapter_number}:{suffix}"


def _cover_path(script_path: Path, script: VoicebookScript) -> Path | None:
    if not script.cover:
        return None
    cover = (script_path.parent / script.cover).resolve()
    if not cover.is_file():
        raise FileNotFoundError(f"脚本指定的封面不存在：{cover}")
    return cover


def _encode_mp3(
    wav: Path,
    output: Path,
    script: VoicebookScript,
    title: str,
    cover: Path | None,
    track: int | None = None,
    *,
    work: WorkProgress | None = None,
    cancel_file: Path | None = None,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav)]
    if cover:
        command.extend(
            (
                "-i",
                str(cover),
                "-map",
                "0:a",
                "-map",
                "1:v",
                "-c:v",
                "copy",
                "-disposition:v",
                "attached_pic",
            )
        )
    command.extend(
        (
            "-c:a",
            "libmp3lame",
            "-b:a",
            MP3_BITRATE,
            "-id3v2_version",
            "3",
            "-metadata",
            f"title={title}",
            "-metadata",
            f"album={script.title}",
            "-metadata",
            f"artist={script.author or 'voicebook-tool'}",
        )
    )
    if track is not None:
        command.extend(("-metadata", f"track={track}"))
    command.append(str(output))
    _run_media(command, work=work, cancel_file=cancel_file)
    probe = _run_media(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name:format=duration",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        work=work,
        cancel_file=cancel_file,
    )
    payload = json.loads(probe.stdout)
    codecs = {stream.get("codec_name") for stream in payload.get("streams", [])}
    duration = float(payload.get("format", {}).get("duration", 0))
    if "mp3" not in codecs or duration <= 0:
        raise RuntimeError(f"生成的 MP3 无法通过 ffprobe 校验：{output}")
    return round(duration * 1000)


def _safe_manifest_file(output_dir: Path, relative: str) -> Path | None:
    candidate = (output_dir / relative).resolve()
    try:
        candidate.relative_to(output_dir.resolve())
    except ValueError:
        return None
    return candidate


def _resume_chapter(output_dir: Path, record: dict) -> tuple[Path, Path] | None:
    audio = _safe_manifest_file(output_dir, str(record.get("audio", "")))
    timeline = _safe_manifest_file(output_dir, str(record.get("timeline", "")))
    if not audio or not timeline or not audio.is_file() or not timeline.is_file():
        return None
    expected = str(record.get("sha256", ""))
    if expected and _sha256_file(audio) != expected:
        return None
    return audio, timeline


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
    force: bool = False,
    synthesizer: Synthesizer | None = None,
    progress: ProgressEmitter | None = None,
    cancel_file: Path | None = None,
    resume: bool = False,
    concurrency: int | None = None,
    max_retries: int = 2,
    retry_backoff: float = 1.0,
    max_wait_seconds: float = 300.0,
    edge_budget: EdgeBudget | None = None,
    edge_budget_path: Path | None = None,
    edge_interval: float = 5.0,
    edge_max_concurrency: int = 1,
    edge_request_limit: int = 0,
    edge_window_seconds: float = 3600.0,
    edge_cooldown_seconds: float = 30.0,
) -> list[Path]:
    concurrency = concurrency if concurrency is not None else (2 if engine == "qwen3tts" else 1)
    if not 1 <= concurrency <= 32:
        raise ValueError("concurrency 必须在 1 到 32 之间")
    if not 0 <= max_retries <= 10:
        raise ValueError("max_retries 必须在 0 到 10 之间")
    if not 0 <= retry_backoff <= 30:
        raise ValueError("retry_backoff 必须在 0 到 30 之间")
    if not 0 <= max_wait_seconds <= 86400:
        raise ValueError("max_wait_seconds 必须在 0 到 86400 之间")
    if engine == "edgetts" and edge_budget is None and (synthesizer is None or edge_budget_path is not None):
        edge_budget = EdgeBudget(edge_budget_path or Path(os.getenv("VOICEBOOK_EDGE_BUDGET", str(Path.home() / ".cache/voicebook/edge-budget.sqlite3"))),
                                 interval=edge_interval, concurrency=edge_max_concurrency,
                                 request_limit=edge_request_limit, window_seconds=edge_window_seconds,
                                 cooldown_seconds=edge_cooldown_seconds)
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
    base_cast = assign_cast(
        script.characters,
        script.chapters,
        engine,
        script.protagonist_voices.get(engine, {}),
    )
    logical_by_number = {}
    for chapter in chosen:
        title_assignment = base_cast["旁白"]
        logical = [
            (
                ScriptSegment("旁白", chapter.title),
                title_assignment,
                title_assignment.speed,
            )
        ]
        logical.extend(
            (
                segment,
                *_segment_assignment(segment, character_map, base_cast, script, engine),
            )
            for segment in chapter.segments
            if SPEAKABLE_RE.search(segment.text)
        )
        logical_by_number[chapter.number] = logical
    emitter = progress or ProgressEmitter(stream=None, version=2)
    emitter.snapshot_path = output_dir / ".voicebook" / "progress.v2.json"
    units = [
        _unit_id(chapter.number, index) for chapter in chosen for index in range(len(logical_by_number[chapter.number]))
    ]
    work = WorkProgress(emitter, units, len(chosen), concurrency)
    work.budget = edge_budget
    cache_dir = output_dir / ".voicebook" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cover = _cover_path(script_path, script)
    synth = synthesizer or CloudSynthesizer()
    output_files: list[Path] = []
    chapter_records: list[dict] = []
    manifest_path = output_dir / "manifest.v2.json"
    script_sha256 = _sha256_bytes(script_path.read_bytes())
    manifest_base = {
        "format": "voicebook-project",
        "version": 2,
        "engine": engine,
        "script_sha256": script_sha256,
        "title": script.title,
        "author": script.author,
        "selected_chapters": numbers,
        "task_id": emitter.task_id,
        "attempt_id": emitter.attempt_id,
        "cast": {name: asdict(assignment) for name, assignment in base_cast.items()},
    }
    resumed: dict[int, dict] = {}
    if resume and not force and manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        if (
            previous.get("version") == 2
            and previous.get("engine") == engine
            and previous.get("script_sha256") == script_sha256
        ):
            resumed = {int(record["number"]): record for record in previous.get("chapters", [])}

    def write_manifest(status: str, **extra) -> None:
        _atomic_json(
            manifest_path,
            {
                **manifest_base,
                "status": status,
                "chapters": chapter_records,
                "chapter_count": len(chapter_records),
                "duration_ms": sum(int(record.get("duration_ms", 0)) for record in chapter_records),
                **extra,
            },
        )

    write_manifest("generating")
    work.emit("phase_started", job_phase="GENERATING")
    try:
        for chapter in chosen:
            check_cancelled(cancel_file)
            previous_record = resumed.get(chapter.number)
            previous_files = _resume_chapter(output_dir, previous_record) if previous_record else None
            if previous_record and previous_files:
                chapter_records.append(previous_record)
                output_files.append(previous_files[0])
                for index in range(len(logical_by_number[chapter.number])):
                    unit = _unit_id(chapter.number, index)
                    work.states[unit] = "completed"
                    work.cached.add(unit)
                work.chapters_completed += 1
                work.emit(
                    "chapter_completed",
                    chapter_number=chapter.number,
                    audio=previous_record["audio"],
                    timeline=previous_record["timeline"],
                    duration_ms=previous_record["duration_ms"],
                    size_bytes=previous_record["size_bytes"],
                    sha256=previous_record["sha256"],
                    segment_count=len(logical_by_number[chapter.number]) - 1,
                    resumed=True,
                )
                continue

            logical = logical_by_number[chapter.number]
            work.stage = "synthesizing"
            work.emit(
                "chapter_started",
                chapter_number=chapter.number,
                title=chapter.title,
                total_segments=max(0, len(logical) - 1),
            )
            audio_parts: list[Path] = []
            timeline_segments: list[dict] = []
            cursor_ms = 0
            rendered = _render_with_probe(
                logical,
                engine,
                cache_dir,
                synth,
                force,
                work=work,
                chapter_number=chapter.number,
                cancel_file=cancel_file,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
                edge_budget=edge_budget,
                max_wait_seconds=max_wait_seconds,
            )
            work.stage = "assembling"
            work.status = "running"
            work.emit("stage_changed", chapter_number=chapter.number)
            for index, (
                (segment, assignment, speed),
                (audio, fingerprint, cache_hit),
            ) in enumerate(zip(logical, rendered)):
                check_cancelled(cancel_file)
                duration_ms = _wav_duration_ms(audio)
                audio_parts.append(audio)
                if index > 0:
                    segment_index = index - 1
                    locator = segment.locator or {
                        "type": "text-segment",
                        "chapter_number": chapter.number,
                        "segment_index": segment_index,
                    }
                    timeline_segments.append(
                        {
                            "id": f"seg-{segment_index:06d}",
                            "index": segment_index,
                            "start_ms": cursor_ms,
                            "end_ms": cursor_ms + duration_ms,
                            "text": segment.text,
                            "character": segment.character,
                            "voice": assignment.voice,
                            "speed": round(speed, 4),
                            "locator": locator,
                        }
                    )
                cursor_ms += duration_ms
                if index < len(logical) - 1:
                    pause_ms = TITLE_PAUSE_MS if index == 0 else SEGMENT_PAUSE_MS
                    pause = cache_dir / f"silence-{pause_ms}ms.wav"
                    if not pause.exists():
                        write_wav_silence_like(audio, pause, pause_ms)
                    audio_parts.append(pause)
                    cursor_ms += pause_ms

            final_pause = cache_dir / f"silence-{CHAPTER_END_PAUSE_MS}ms.wav"
            if not final_pause.exists():
                write_wav_silence_like(audio_parts[-1], final_pause, CHAPTER_END_PAUSE_MS)
            audio_parts.append(final_pause)
            cursor_ms += CHAPTER_END_PAUSE_MS
            chapter_wav = output_dir / ".voicebook" / f"chapter-{chapter.number:04d}.wav"
            check_cancelled(cancel_file)
            _concat_wavs(audio_parts, chapter_wav, work=work, cancel_file=cancel_file)
            check_cancelled(cancel_file)
            wav_duration_ms = _wav_duration_ms(chapter_wav)
            timeline_path = output_dir / "timelines" / f"{chapter.number:04d}.json"
            timeline_relative = timeline_path.relative_to(output_dir).as_posix()
            _atomic_json(
                timeline_path,
                {
                    "format": "voicebook-timeline",
                    "version": 1,
                    "chapter_number": chapter.number,
                    "source_key": chapter.source_key,
                    "duration_ms": wav_duration_ms,
                    "segments": timeline_segments,
                },
            )
            chapter_mp3 = output_dir / "chapters" / f"{chapter.number:04d}.mp3"
            mp3_duration_ms = _encode_mp3(
                chapter_wav,
                chapter_mp3,
                script,
                chapter.title,
                cover,
                chapter.number,
                work=work,
                cancel_file=cancel_file,
            )
            check_cancelled(cancel_file)
            record = {
                "number": chapter.number,
                "source_key": chapter.source_key,
                "title": chapter.title,
                "audio": chapter_mp3.relative_to(output_dir).as_posix(),
                "timeline": timeline_relative,
                "duration_ms": mp3_duration_ms,
                "timeline_duration_ms": wav_duration_ms,
                "size_bytes": chapter_mp3.stat().st_size,
                "sha256": _sha256_file(chapter_mp3),
                "segment_count": len(timeline_segments),
            }
            chapter_records.append(record)
            output_files.append(chapter_mp3)
            write_manifest("generating")
            work.chapters_completed += 1
            work.emit("chapter_completed", chapter_number=chapter.number, **record)

        check_cancelled(cancel_file)
        work.stage = "finalizing"
        work.emit("stage_changed")
        write_manifest("completed")
        work.stage = "completed"
        work.status = "completed"
        work.emit(
            "completed",
            manifest=manifest_path.name,
            chapter_count=len(chapter_records),
            duration_ms=sum(record["duration_ms"] for record in chapter_records),
        )
        return output_files
    except GenerationCancelled:
        write_manifest("cancelled")
        for unit, state in work.states.items():
            if state in {"pending", "active", "retrying", "queued"}:
                work.states[unit] = "cancelled"
        work.active_requests = 0
        work.status = "cancelled"
        work.emit("cancelled", retryable=True)
        raise
    except Exception as exc:
        write_manifest("failed", error=safe_error(exc))
        work.active_requests = 0
        work.status = "failed"
        retryable, _ = retry_details(exc)
        work.waiting = None
        work.emit("failed", code=type(exc).__name__, message=safe_error(exc), retryable=retryable, reason=error_info(exc).reason)
        raise


def convert_book(
    input_path: Path,
    output_dir: Path,
    *,
    engine: str = DEFAULT_ENGINE,
    chapters: str | None = None,
    force: bool = False,
    csi_model: Path | None = None,
    synthesizer: Synthesizer | None = None,
    progress: ProgressEmitter | None = None,
    cancel_file: Path | None = None,
    resume: bool = False,
    concurrency: int | None = None,
    max_retries: int = 2,
    retry_backoff: float = 1.0,
    max_wait_seconds: float = 300.0,
    edge_budget: EdgeBudget | None = None,
    edge_budget_path: Path | None = None,
    edge_interval: float = 5.0,
    edge_max_concurrency: int = 1,
    edge_request_limit: int = 0,
    edge_window_seconds: float = 3600.0,
    edge_cooldown_seconds: float = 30.0,
) -> list[Path]:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / "book.script"
    if progress:
        progress.emit("phase_started", job_phase="INSPECTING")
    check_cancelled(cancel_file)
    inspect_book(input_path, script_path, chapters=chapters, csi_model=csi_model)
    check_cancelled(cancel_file)
    # inspect 已经裁剪过章节，generate 不应再次按原书总章号过滤。
    return generate_audio(
        script_path,
        output_dir,
        engine=engine,
        force=force,
        synthesizer=synthesizer,
        progress=progress,
        cancel_file=cancel_file,
        resume=resume,
        concurrency=concurrency,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
        max_wait_seconds=max_wait_seconds,
        edge_budget=edge_budget,
        edge_budget_path=edge_budget_path,
        edge_interval=edge_interval,
        edge_max_concurrency=edge_max_concurrency,
        edge_request_limit=edge_request_limit,
        edge_window_seconds=edge_window_seconds,
        edge_cooldown_seconds=edge_cooldown_seconds,
    )
