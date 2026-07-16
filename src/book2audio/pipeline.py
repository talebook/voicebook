"""端到端流水线：TXT -> 章节 -> 对白/旁白 -> TTS 合成 -> ffmpeg 拼接为 MP4 有声书

输出模式按 -o 后缀/参数分流：
  .mp4           合成有声书（--multi-voice 多角色，支持 --engine edge/qwen）
  .md            只读识别报告（人工查看）
  .script        可编辑配音脚本（中间格式，改完用 --from-script 回灌合成）
  --from-script  从配音脚本直接合成，跳过识别（用人工校正后的归属）
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

import edge_tts

from .parser import Chapter, split_chapters, split_segments

# 双音色基线：旁白沉稳男声 + 对白统一年轻男声（--multi-voice 时按角色画像分配）
NARRATOR_VOICE = "zh-CN-YunjianNeural"
DIALOGUE_VOICE = "zh-CN-YunxiNeural"

CONCURRENCY = 4
MAX_RETRIES = 3
SUPPORTED_ENGINES = {"edge", "qwen"}
QWEN_CHAPTER_END_PAUSE_MS = 700
QWEN_SEGMENT_PAUSE_MS = 250
QWEN_TITLE_PAUSE_MS = 900


def _validate_engine(engine: str):
    if engine not in SUPPORTED_ENGINES:
        raise SystemExit(
            f"不支持 TTS 引擎: {engine}。当前支持 edge、qwen；"
            "本地模型需先在 research/ 单独评估，单模型目标体积约 500MB。"
        )


async def _synth_one(text: str, voice: str, out_path: Path, sem: asyncio.Semaphore,
                     rate: str = "+0%", pitch: str = "+0Hz"):
    async with sem:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(out_path))
                if out_path.stat().st_size > 0:
                    return
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise RuntimeError(f"edge-tts failed: {text[:30]}...") from e
                await asyncio.sleep(2 * attempt)


def _merge_adjacent(parts):
    """合并相邻同音色片段，减少请求数。"""
    merged = []
    for text, v in parts:
        if merged and merged[-1][1] == v:
            merged[-1] = (merged[-1][0] + "\n" + text, v)
        else:
            merged.append((text, v))
    return merged


def _is_qwen_voice_spec(spec) -> bool:
    """Qwen specs use ``(system_voice, numeric_tempo)``; Cosy uses two strings."""
    return (
        isinstance(spec, tuple)
        and len(spec) == 2
        and isinstance(spec[1], (int, float))
    )


def _multivoice_parts(chapter: Chapter, quotes, voices, narrator_spec=None):
    """识别结果 -> (text, voicespec) 段列表。旁白/拟声/未识别用旁白音，对白用角色音（叠加状态）。"""
    from .casting import NARRATOR, QWEN_DIALOGUE, apply_state

    narrator_spec = narrator_spec or NARRATOR
    dialogue_spec = QWEN_DIALOGUE if voices and _is_qwen_voice_spec(next(iter(voices.values()))) else (
        DIALOGUE_VOICE, "+0%", "+0Hz")

    by_para = {}
    for q in quotes:
        by_para.setdefault(q.para_idx, []).append(q)

    parts = [(chapter.title, narrator_spec)]
    paras = [p.strip() for p in chapter.content.splitlines() if p.strip()]
    for pi, para in enumerate(paras):
        pos = 0
        for q in sorted(by_para.get(pi, []), key=lambda x: x.span[0]):
            if para[pos:q.span[0]].strip():
                parts.append((para[pos:q.span[0]], narrator_spec))
            if q.kind == "sfx" or not q.speaker:
                parts.append((para[q.span[0]:q.span[1]], narrator_spec))
            else:
                spec = voices.get(q.speaker, dialogue_spec)
                parts.append((q.text, apply_state(spec, q.state) if q.state else spec))
            pos = q.span[1]
        if para[pos:].strip():
            parts.append((para[pos:], narrator_spec))
    if _is_qwen_voice_spec(narrator_spec):
        return parts[:1] + _merge_adjacent(parts[1:])
    return _merge_adjacent(parts)


def _script_parts(title: str, segments, resolve, narrator_spec):
    """配音脚本段 -> (text, voicespec) 段列表（与 _multivoice_parts 输出同构）。
    resolve(tag) 把 旁白/音/?/角色名/角色名@变体 解析为音色规格。"""
    parts = [(title, narrator_spec)]
    for tag, text in segments:
        parts.append((text, resolve(tag)))
    if _is_qwen_voice_spec(narrator_spec):
        return parts[:1] + _merge_adjacent(parts[1:])
    return _merge_adjacent(parts)


async def synth_chapter_edge(parts, work_dir: Path, ch_num: int) -> Path:
    """edge-tts 合成一章（parts: [(text,(voice,rate,pitch)),...]），返回章节 mp3。"""
    sem = asyncio.Semaphore(CONCURRENCY)
    seg_dir = work_dir / f"ch{ch_num:04d}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    seg_files, tasks = [], []
    for i, (text, (voice, rate, pitch)) in enumerate(parts):
        f = seg_dir / f"{i:05d}.mp3"
        seg_files.append(f)
        tasks.append(_synth_one(text, voice, f, sem, rate, pitch))
    await asyncio.gather(*tasks)

    list_file = seg_dir / "list.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in seg_files))
    chapter_mp3 = work_dir / f"chapter_{ch_num:04d}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-c", "copy", str(chapter_mp3)], check=True)
    return chapter_mp3


async def synth_chapter_qwen(parts, work_dir: Path, ch_num: int) -> Path:
    """Qwen3TTSAI 合成一章；自动按站点 1000 字上限切分，返回 PCM WAV。"""
    from .tts import Qwen3TTSAIEngine, VoiceSpec, split_tts_text

    engine = Qwen3TTSAIEngine()
    seg_dir = work_dir / f"ch{ch_num:04d}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    logical_segments, tasks = [], []
    index = 0
    for text, spec in parts:
        voice = spec[0]
        tempo = float(spec[1]) if _is_qwen_voice_spec(spec) else 1.0
        segment_files = []
        for chunk in split_tts_text(text):
            out = seg_dir / f"{index:05d}.wav"
            index += 1
            segment_files.append((out, tempo))
            tasks.append(engine.synth(chunk, VoiceSpec(voice), out))
        if segment_files:
            logical_segments.append(segment_files)
    await asyncio.gather(*tasks)

    from .audio import change_pcm16_wav_tempo, smooth_pcm16_wav_edges, write_wav_silence_like
    for segment_files in logical_segments:
        for segment_file, tempo in segment_files:
            change_pcm16_wav_tempo(segment_file, tempo)
            smooth_pcm16_wav_edges(segment_file)

    concat_files = []
    for logical_index, segment_files in enumerate(logical_segments):
        concat_files.extend(path for path, _tempo in segment_files)
        if logical_index == len(logical_segments) - 1:
            continue
        pause_ms = QWEN_TITLE_PAUSE_MS if logical_index == 0 else QWEN_SEGMENT_PAUSE_MS
        pause_file = seg_dir / f"pause_{logical_index:05d}_{pause_ms}ms.wav"
        write_wav_silence_like(segment_files[-1][0], pause_file, pause_ms)
        concat_files.append(pause_file)
    if logical_segments:
        chapter_pause = seg_dir / f"chapter_end_{QWEN_CHAPTER_END_PAUSE_MS}ms.wav"
        write_wav_silence_like(
            logical_segments[-1][-1][0],
            chapter_pause,
            QWEN_CHAPTER_END_PAUSE_MS,
        )
        concat_files.append(chapter_pause)

    list_file = seg_dir / "list.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in concat_files))
    chapter_wav = work_dir / f"chapter_{ch_num:04d}.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-c", "copy", str(chapter_wav)], check=True)
    return chapter_wav


def synth_all_cosyvoice(parts_by_ch, narrator, work_dir: Path):
    """CosyVoice 路径：全书片段一次性批量合成（均摊模型加载），返回各章音频文件。"""
    from .tts import CosyVoiceEngine

    engine = CosyVoiceEngine()
    chapter_segs = {}
    for ch_num, parts in parts_by_ch.items():
        seg_dir = work_dir / f"ch{ch_num:04d}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        segs = []
        for i, (text, spec) in enumerate(parts):
            # cosy 音色是 (wav, text) 二元组；旁白占位（edge 三元组）回退到旁白参考音
            wav, prompt_text = spec if (isinstance(spec, tuple) and len(spec) == 2) else narrator
            out = seg_dir / f"{i:05d}.wav"
            engine._batch.append({"text": text, "prompt_wav": wav,
                                  "prompt_text": prompt_text, "out": str(out)})
            segs.append(out)
        chapter_segs[ch_num] = segs
    print(f"CosyVoice 批量合成 {sum(len(s) for s in chapter_segs.values())} 个片段（CPU较慢，请耐心）...")
    engine.flush()

    chapter_files = []
    for ch_num, segs in chapter_segs.items():
        list_file = work_dir / f"ch{ch_num:04d}/list.txt"
        list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in segs))
        out = work_dir / f"chapter_{ch_num:04d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(list_file), "-c", "copy", str(out)], check=True)
        chapter_files.append(out)
    return chapter_files


def _duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True)
    return int(float(json.loads(out.stdout)["format"]["duration"]) * 1000)


def assemble_mp4(titles: List[str], chapter_files: List[Path], output: Path, work_dir: Path,
                 book_title: str = "book2audio"):
    """拼接所有章节并编码为带章节标记的 MP4（AAC）。"""
    list_file = work_dir / "all_chapters.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in chapter_files))

    meta_lines = [";FFMETADATA1", f"title={book_title}", "artist=book2audio"]
    start = 0
    for title, f in zip(titles, chapter_files):
        end = start + _duration_ms(f)
        meta_lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={title}"]
        start = end
    meta_file = work_dir / "metadata.txt"
    meta_file.write_text("\n".join(meta_lines))

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(list_file), "-i", str(meta_file), "-map_metadata", "1",
                    "-c:a", "aac", "-b:a", "64k", str(output)], check=True)


def _resolve_voices(profiles, engine):
    """画像 -> 音色表 + 旁白音。返回 (voices, narrator_spec)。"""
    if engine == "cosyvoice":
        from .casting import assign_cosy_voices
        bank = json.loads(Path("voicebank/bank.json").read_text())
        voices = assign_cosy_voices(profiles, bank)
        nar = next(e for e in bank["voices"] if e["id"] == bank["narrator"])
        return voices, (nar["wav"], nar["text"])
    if engine == "qwen":
        from .casting import QWEN_NARRATOR, assign_qwen_voices
        return assign_qwen_voices(profiles), QWEN_NARRATOR
    from .casting import NARRATOR, assign_voices
    return assign_voices(profiles), NARRATOR


def _synthesize(parts_by_ch, titles, output, engine, book_title, keep_temp):
    work_dir = Path(tempfile.mkdtemp(prefix="book2audio_"))
    try:
        if engine == "cosyvoice":
            bank = json.loads(Path("voicebank/bank.json").read_text())
            nar = next(e for e in bank["voices"] if e["id"] == bank["narrator"])
            chapter_files = synth_all_cosyvoice(parts_by_ch, (nar["wav"], nar["text"]), work_dir)
        elif engine == "qwen":
            chapter_files = []
            for ch_num, parts in parts_by_ch.items():
                print(f"[ch{ch_num}] qwen 合成 {len(parts)} 段...")
                chapter_files.append(asyncio.run(synth_chapter_qwen(parts, work_dir, ch_num)))
        else:
            chapter_files = []
            for ch_num, parts in parts_by_ch.items():
                print(f"[ch{ch_num}] edge 合成 {len(parts)} 段...")
                chapter_files.append(asyncio.run(synth_chapter_edge(parts, work_dir, ch_num)))
        print("拼接并编码 MP4...")
        assemble_mp4(titles, chapter_files, output, work_dir, book_title)
        print(f"完成: {output}")
    finally:
        if not keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


def run_from_script(script_path: Path, output: Path, engine: str = "edge", keep_temp: bool = False):
    """从人工校正后的配音脚本直接合成，跳过识别。"""
    _validate_engine(engine)
    from .casting import AGE_STAGES, CharacterProfile, apply_state
    from .script import parse_script

    cast, chapters = parse_script(script_path)
    profiles = {n: CharacterProfile(name=n, gender=g, age_stage=s) for n, (g, s, _) in cast.items()}
    voices, narrator_spec = _resolve_voices(profiles, engine)
    # 应用音色覆盖
    for n, (_, _, override) in cast.items():
        if override:
            if engine == "cosyvoice":
                bank = json.loads(Path("voicebank/bank.json").read_text())
                e = next((e for e in bank["voices"] if e["id"] == override), None)
                if e:
                    voices[n] = (e["wav"], e["text"])
            elif engine == "qwen":
                from .casting import qwen_tempo_for_age
                voices[n] = (override, qwen_tempo_for_age(profiles[n].age_stage))
            else:
                voices[n] = (override, "+0%", "+0Hz")

    def resolve(tag):
        if tag in ("旁白", "音", "?"):
            return narrator_spec
        if tag in voices:                      # 精确命中（含 角色名@变体 的角色表行）
            return voices[tag]
        name, _, variant = tag.partition("@")
        base = voices.get(name, narrator_spec)
        if not variant:
            return base
        if variant in AGE_STAGES and name in cast:   # 快捷年龄段切换 → 重选音色
            g = cast[name][0]
            prof = {name: CharacterProfile(name=name, gender=g if g != "unknown" else "male",
                                           age_stage=variant)}
            return _resolve_voices(prof, engine)[0][name]
        return apply_state(base, variant)            # 否则按状态叠加韵律

    parts_by_ch, titles = {}, []
    for i, (title, segs) in enumerate(chapters, 1):
        parts_by_ch[i] = _script_parts(title, segs, resolve, narrator_spec)
        titles.append(title)
    print(f"从脚本合成 {len(chapters)} 章，{len(cast)} 个角色，引擎 {engine}")
    _synthesize(parts_by_ch, titles, output, engine, script_path.stem, keep_temp)


def run(input_txt: Path, output: Path, chapter_range: range, keep_temp: bool = False,
        multi_voice: bool = False, csi_model_dir: Path = Path("models/csi-v1"),
        engine: str = "edge"):
    _validate_engine(engine)
    text = input_txt.read_text(encoding="utf-8")
    all_chapters = split_chapters(text)
    chapters = [c for c in all_chapters if c.num in chapter_range]
    if not chapters:
        raise SystemExit(f"未找到指定章节（全书共 {len(all_chapters)} 章）")
    print(f"共 {len(all_chapters)} 章，本次合成 {len(chapters)} 章: {chapters[0].title} .. {chapters[-1].title}")

    report_mode = output.suffix == ".md"
    script_mode = output.suffix == ".script"
    if report_mode or script_mode:
        multi_voice = True

    quotes_by_ch, voices, profiles, narrator_spec = {}, None, {}, None
    if multi_voice:
        from .attribution import Attributor
        from .casting import build_profiles
        attributor = Attributor(csi_model_dir=csi_model_dir if csi_model_dir.exists() else None)
        selected = "\n".join(c.content for c in chapters)
        attributor.build_names(selected)
        for ch in chapters:
            print(f"识别 {ch.title} 说话人...")
            quotes_by_ch[ch.num] = attributor.attribute(ch.content)
        speakers = {q.speaker for qs in quotes_by_ch.values() for q in qs if q.speaker}
        profiles = build_profiles(selected, speakers)
        voices, narrator_spec = _resolve_voices(profiles, engine)
        print("角色音色分配:")
        for n in sorted(voices):
            p = profiles[n]
            tag = voices[n][0]
            print(f"  {n}: {p.gender}/{p.age_stage} → {Path(tag).stem if '/' in str(tag) else tag.replace('zh-CN-', '')}")

    if report_mode:
        from .report import write_report
        write_report(input_txt.stem, chapters, quotes_by_ch, profiles, voices, output)
        print(f"完成: {output}")
        return
    if script_mode:
        from .script import write_script
        write_script(input_txt.stem, chapters, quotes_by_ch, profiles, voices, output)
        print(f"完成: {output}（编辑后用 --from-script 回灌合成）")
        return

    if multi_voice:
        parts_by_ch = {
            ch.num: _multivoice_parts(ch, quotes_by_ch[ch.num], voices, narrator_spec)
            for ch in chapters
        }
    else:
        if engine == "cosyvoice":
            raise SystemExit("cosyvoice 引擎当前仅支持 --multi-voice 模式")
        if engine == "qwen":
            from .casting import QWEN_DIALOGUE, QWEN_NARRATOR
            narration_spec, dialogue_spec = QWEN_NARRATOR, QWEN_DIALOGUE
        else:
            narration_spec = (NARRATOR_VOICE, "+0%", "+0Hz")
            dialogue_spec = (DIALOGUE_VOICE, "+0%", "+0Hz")
        parts_by_ch = {}
        for ch in chapters:
            ss = split_segments(ch.content)
            parts_by_ch[ch.num] = [(ch.title, narration_spec)] + [
                (s.text, narration_spec if s.kind == "narration" else dialogue_spec)
                for s in ss]
    titles = [ch.title for ch in chapters]
    _synthesize(parts_by_ch, titles, output, engine, input_txt.stem, keep_temp)
