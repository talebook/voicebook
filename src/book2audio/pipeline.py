"""端到端流水线：TXT -> 章节 -> 对白/旁白 -> edge-tts 合成 -> ffmpeg 拼接为 MP4 有声书"""

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
                    raise RuntimeError(f"TTS failed after {MAX_RETRIES} tries: {text[:30]}...") from e
                await asyncio.sleep(2 * attempt)


def _multivoice_parts(chapter: Chapter, quotes, voices):
    """按说话人归属结果构造 (text, (voice, rate, pitch)) 列表。"""
    from .casting import NARRATOR

    by_para = {}
    for q in quotes:
        by_para.setdefault(q.para_idx, []).append(q)

    parts = [(chapter.title, NARRATOR)]
    paras = [p.strip() for p in chapter.content.splitlines() if p.strip()]
    for pi, para in enumerate(paras):
        pos = 0
        for q in sorted(by_para.get(pi, []), key=lambda x: x.span[0]):
            if para[pos:q.span[0]].strip():
                parts.append((para[pos:q.span[0]], NARRATOR))
            if q.kind == "sfx" or not q.speaker:
                # 拟声词/未识别 → 旁白连引号一起读
                parts.append((para[q.span[0]:q.span[1]], NARRATOR))
            else:
                parts.append((q.text, voices.get(q.speaker, (DIALOGUE_VOICE, "+0%", "+0Hz"))))
            pos = q.span[1]
        if para[pos:].strip():
            parts.append((para[pos:], NARRATOR))
    # 合并相邻同音色片段，减少请求数
    merged = []
    for text, v in parts:
        if merged and merged[-1][1] == v:
            merged[-1] = (merged[-1][0] + "\n" + text, v)
        else:
            merged.append((text, v))
    return merged


async def synth_chapter(chapter: Chapter, work_dir: Path, quotes=None, voices=None) -> Path:
    """合成单章音频，返回章节 mp3 路径。quotes/voices 提供时启用多角色音色。"""
    if quotes is not None:
        parts = _multivoice_parts(chapter, quotes, voices)
    else:
        segments = split_segments(chapter.content)
        parts = [(chapter.title, (NARRATOR_VOICE, "+0%", "+0Hz"))] + [
            (s.text, ((NARRATOR_VOICE if s.kind == "narration" else DIALOGUE_VOICE), "+0%", "+0Hz"))
            for s in segments]

    sem = asyncio.Semaphore(CONCURRENCY)
    seg_dir = work_dir / f"ch{chapter.num:04d}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    seg_files = []
    for i, (text, (voice, rate, pitch)) in enumerate(parts):
        f = seg_dir / f"{i:05d}.mp3"
        seg_files.append(f)
        tasks.append(_synth_one(text, voice, f, sem, rate, pitch))
    await asyncio.gather(*tasks)

    # ffmpeg concat 合并段落
    list_file = seg_dir / "list.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in seg_files))
    chapter_mp3 = work_dir / f"chapter_{chapter.num:04d}.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(chapter_mp3)],
        check=True,
    )
    return chapter_mp3


def _duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return int(float(json.loads(out.stdout)["format"]["duration"]) * 1000)


def assemble_mp4(chapters: List[Chapter], chapter_files: List[Path], output: Path, work_dir: Path):
    """拼接所有章节并编码为带章节标记的 MP4（AAC）。"""
    list_file = work_dir / "all_chapters.txt"
    list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in chapter_files))

    # 生成 FFMETADATA 章节标记
    meta_lines = [";FFMETADATA1", "title=玄鉴仙族", "artist=book2audio"]
    start = 0
    for ch, f in zip(chapters, chapter_files):
        end = start + _duration_ms(f)
        meta_lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={ch.title}"]
        start = end
    meta_file = work_dir / "metadata.txt"
    meta_file.write_text("\n".join(meta_lines))

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-i", str(meta_file), "-map_metadata", "1",
         "-c:a", "aac", "-b:a", "64k", str(output)],
        check=True,
    )


def synth_all_cosyvoice(chapters, quotes_by_ch, cosy_voices, narrator, work_dir: Path):
    """CosyVoice 路径：全书片段一次性批量合成（均摊模型加载），返回各章音频文件。"""
    from .tts import CosyVoiceEngine

    engine = CosyVoiceEngine()
    chapter_segs = {}
    for ch in chapters:
        parts = _multivoice_parts(ch, quotes_by_ch[ch.num], cosy_voices)
        seg_dir = work_dir / f"ch{ch.num:04d}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        segs = []
        for i, (text, voice) in enumerate(parts):
            # cosy 音色是 (wav, text) 二元组；旁白占位（edge 三元组）回退到旁白参考音
            wav, prompt_text = voice if (isinstance(voice, tuple) and len(voice) == 2) else narrator
            out = seg_dir / f"{i:05d}.wav"
            engine._batch.append({"text": text, "prompt_wav": wav,
                                  "prompt_text": prompt_text, "out": str(out)})
            segs.append(out)
        chapter_segs[ch.num] = segs
    print(f"CosyVoice 批量合成 {sum(len(s) for s in chapter_segs.values())} 个片段（CPU较慢，请耐心）...")
    engine.flush()

    chapter_files = []
    for ch in chapters:
        list_file = work_dir / f"ch{ch.num:04d}/list.txt"
        list_file.write_text("".join(f"file '{f.resolve()}'\n" for f in chapter_segs[ch.num]))
        out = work_dir / f"chapter_{ch.num:04d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(list_file), "-c", "copy", str(out)], check=True)
        chapter_files.append(out)
    return chapter_files


def run(input_txt: Path, output: Path, chapter_range: range, keep_temp: bool = False,
        multi_voice: bool = False, csi_model_dir: Path = Path("models/csi-v1"),
        engine: str = "edge"):
    text = input_txt.read_text(encoding="utf-8")
    all_chapters = split_chapters(text)
    chapters = [c for c in all_chapters if c.num in chapter_range]
    if not chapters:
        raise SystemExit(f"未找到指定章节（全书共 {len(all_chapters)} 章）")
    print(f"共 {len(all_chapters)} 章，本次合成 {len(chapters)} 章: {chapters[0].title} .. {chapters[-1].title}")

    report_mode = output.suffix == ".md"
    if report_mode:
        multi_voice = True
    quotes_by_ch, voices = {}, None
    if multi_voice:
        from .attribution import Attributor
        from .casting import assign_voices, build_profiles
        attributor = Attributor(csi_model_dir=csi_model_dir if csi_model_dir.exists() else None)
        selected = "\n".join(c.content for c in chapters)
        attributor.build_names(selected)
        # 先完成全部归属（CSI 会动态发现新角色），再建画像和音色表
        for ch in chapters:
            print(f"识别 {ch.title} 说话人...")
            quotes_by_ch[ch.num] = attributor.attribute(ch.content)
        # 只给实际开口的角色建画像/分音色（注册表保持宽松，仅用于归属映射）
        speakers = {q.speaker for qs in quotes_by_ch.values() for q in qs if q.speaker}
        profiles = build_profiles(selected, speakers)
        if engine == "cosyvoice":
            from .casting import assign_cosy_voices
            bank = json.loads(Path("voicebank/bank.json").read_text())
            voices = assign_cosy_voices(profiles, bank)
            print("角色音色分配 (cosyvoice 参考音):")
            for n, (wav, _) in sorted(voices.items()):
                p = profiles[n]
                print(f"  {n}: {p.gender}/{p.age_stage} → {Path(wav).stem}")
        else:
            voices = assign_voices(profiles)
            print("角色音色分配:")
            for n, (v, rate, pitch) in sorted(voices.items()):
                p = profiles[n]
                print(f"  {n}: {p.gender}/{p.age_stage}{f'/{p.age}岁' if p.age else ''} → {v.replace('zh-CN-', '')} {rate} {pitch}")

    if report_mode:
        from .report import write_report
        write_report(input_txt.stem, chapters, quotes_by_ch, profiles, voices, output)
        print(f"完成: {output}")
        return

    work_dir = Path(tempfile.mkdtemp(prefix="book2audio_"))
    try:
        if engine == "cosyvoice":
            if not multi_voice:
                raise SystemExit("cosyvoice 引擎当前仅支持 --multi-voice 模式")
            bank = json.loads(Path("voicebank/bank.json").read_text())
            nar = next(e for e in bank["voices"] if e["id"] == bank["narrator"])
            chapter_files = synth_all_cosyvoice(chapters, quotes_by_ch, voices,
                                                (nar["wav"], nar["text"]), work_dir)
        else:
            chapter_files = []
            for ch in chapters:
                print(f"[{ch.num}/{chapters[-1].num}] 合成 {ch.title} ({len(ch.content)} 字)...")
                chapter_files.append(asyncio.run(synth_chapter(ch, work_dir, quotes_by_ch.get(ch.num), voices)))
        print("拼接并编码 MP4...")
        assemble_mp4(chapters, chapter_files, output, work_dir)
        print(f"完成: {output}")
    finally:
        if not keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)
