"""配音脚本（中间格式）：可读、可编辑、可回灌合成。

与 report.py(.md 只读报告) 的区别：本格式能被 parse_script 解析回流水线驱动 TTS，
用于人工审查/校正——机器先填好 93% 正确的归属，人只改错的几行。

格式：
    ## 角色表
    李项平 | male | 少年 |              # 末列"音色覆盖"留空=按性别/年龄自动选；填则强制
    李长湖 | male | 少年 |              # 基准音色
    李长湖@老年 | male | 老年 |         # 变体：同角色不同年龄/状态，单独一行(@后缀)

    ## 第一章 初入
    无标签的整行就是旁白，直接写正文即可。
    [陆江仙] 将《太阴吐纳练气诀》交出
    [陆江仙@虚弱] 咳……扶我起来            # @状态：虚弱/愤怒/冷淡/低语/悲伤/急切(自动识别,可改)
    [李长湖@老年] 我老了啊……             # @年龄段：童年/少年/青年/中年/老年(切换音色)
    [音] 咣当！                          # 音效/拟声，旁白嗓音读
    [?] 我好像……挂了？                   # 未识别，人工把 ? 改成角色名

标签：无标签=旁白 [音]=拟声 [?]=未识别 [角色名]=对白 [角色名@变体]=该角色的年龄/状态变体
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .parser import Chapter

NARRATION_TAGS = {"旁白", "音", "?"}
TAG_RE = re.compile(r"\[([^\]]*)\]\s?(.*)")


def _segments(chapter: Chapter, quotes) -> List[Tuple[str, str]]:
    """章节正文线性化为 (tag, text) 段序列，与 report/合成的切分一致。"""
    by_para: Dict[int, list] = {}
    for q in quotes:
        by_para.setdefault(q.para_idx, []).append(q)
    paras = [p.strip() for p in chapter.content.splitlines() if p.strip()]
    segs: List[Tuple[str, str]] = []
    for pi, para in enumerate(paras):
        pos = 0
        for q in sorted(by_para.get(pi, []), key=lambda x: x.span[0]):
            pre = para[pos:q.span[0]].strip()
            if pre:
                segs.append(("旁白", pre))
            if q.kind == "sfx":
                segs.append(("音", q.text))
            elif q.speaker:
                tag = f"{q.speaker}@{q.state}" if q.state else q.speaker
                segs.append((tag, q.text))
            else:
                segs.append(("?", q.text))
            pos = q.span[1]
        tail = para[pos:].strip()
        if tail:
            segs.append(("旁白", tail))
    return segs


def write_script(book_name: str, chapters: List[Chapter], quotes_by_ch: Dict,
                 profiles: Dict, voices: Dict, output: Path):
    lines = [
        f"# {book_name} 配音脚本（中间格式，可编辑后回灌合成）",
        "# 用法：改完此文件后  uv run python -m book2audio --from-script 本文件 -o out.mp4 [--engine edge|qwen]",
        "# 标签：无标签整行=旁白  [角色名]=对白  [音]=拟声  [?]=未识别(请改成角色名)",
        "#       [角色名@状态]=虚弱/愤怒/冷淡/低语/悲伤/急切(自动识别,可改)  [角色名@年龄段]=童年/少年/青年/中年/老年(切音色)",
        "# 改音色：编辑下方角色表 性别/年龄段，或末列写音色覆盖；同角色多年龄→单独加 角色名@老年 行",
        "",
        "## 角色表",
        "# 角色 | 性别 | 年龄段 | 音色覆盖（留空=自动）",
    ]
    for n in sorted(profiles):
        p = profiles[n]
        cur = voices.get(n)
        hint = ""
        if cur:
            hint = f"  # 当前自动→ {Path(cur[0]).stem if '/' in str(cur[0]) else cur[0].replace('zh-CN-', '')}"
        lines.append(f"{n} | {p.gender} | {p.age_stage} | {hint}")
    lines.append("")

    for ch in chapters:
        lines += [f"## {ch.title}", ""]
        for tag, text in _segments(ch, quotes_by_ch[ch.num]):
            lines.append(text if tag == "旁白" else f"[{tag}] {text}")
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def parse_script(path: Path):
    """解析配音脚本。返回 (cast, chapters)：
    cast: {name: (gender, age_stage, override_or_None)}
    chapters: [(title, [(tag, text), ...]), ...]
    """
    cast: Dict[str, tuple] = {}
    chapters: List[Tuple[str, list]] = []
    section = None  # "cast" | "chapter"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            head = line[3:].strip()
            if head == "角色表":
                section = "cast"
            else:
                section = "chapter"
                chapters.append((head, []))
            continue
        if line.lstrip().startswith("#"):
            continue  # 注释
        if section == "cast" and "|" in line:
            cols = [c.strip() for c in line.split("#", 1)[0].split("|")]
            name = cols[0]
            gender = cols[1] if len(cols) > 1 and cols[1] else "unknown"
            stage = cols[2] if len(cols) > 2 and cols[2] else "青年"
            override = cols[3] if len(cols) > 3 and cols[3] else None
            if name:
                cast[name] = (gender, stage, override)
            continue
        if section == "chapter" and chapters:
            body = line.strip()
            m = TAG_RE.match(body)
            if m and len(m.group(1)) <= 20:  # [标签] 对白/音效；标签过长视为正文中的方括号
                chapters[-1][1].append((m.group(1).strip(), m.group(2)))
            else:                            # 无标签整行 = 旁白
                chapters[-1][1].append(("旁白", body))
    return cast, chapters


# ---------- voicebook-script v1 ----------

SCRIPT_FORMAT = "voicebook-script"
SCRIPT_VERSION = 1
ROLE_COLUMNS = ("角色", "定位", "类型", "性别", "年龄段", "地域", "音色描述", "语速", "音色覆盖")
POSITIONS = {"旁白", "主角", "重要角色", "配角", "群体", "未知"}
CHARACTER_TYPES = {"人类", "机器人", "怪兽", "妖怪", "灵兽", "鬼魂", "神明", "其他非人类"}
GENDERS = {"男", "女", "中性", "未知"}
AGE_GROUPS = {"童年", "少年", "青年", "中年", "老年", "幼体", "成年", "古老", "未知"}
SPEED_RE = re.compile(r"^x(0\.\d+|1(?:\.\d+)?)$")


@dataclass
class ScriptCharacter:
    name: str
    position: str = "配角"
    character_type: str = "人类"
    gender: str = "未知"
    age_group: str = "青年"
    region: str = "未知"
    voice_description: str = ""
    speed: str = "自动"
    voice_overrides: dict[str, str] = field(default_factory=dict)

    def speed_multiplier(self) -> float:
        if self.speed == "自动":
            return 1.0
        _validate_speed(self.speed)
        return float(self.speed[1:])


@dataclass
class ScriptSegment:
    tag: str
    text: str

    @property
    def character(self) -> str:
        return self.tag.split("@", 1)[0]

    @property
    def state(self) -> str:
        return self.tag.split("@", 1)[1] if "@" in self.tag else ""


@dataclass
class ScriptChapter:
    number: int
    title: str
    segments: list[ScriptSegment] = field(default_factory=list)
    volume: str | None = None


@dataclass
class VoicebookScript:
    title: str
    description: str = "多角色有声书配音脚本"
    author: str = ""
    language: str = "zh-CN"
    source: str = ""
    cover: str = ""
    protagonist_voices: dict[str, dict[str, str]] = field(default_factory=dict)
    characters: list[ScriptCharacter] = field(default_factory=list)
    chapters: list[ScriptChapter] = field(default_factory=list)
    extra_meta: dict[str, Any] = field(default_factory=dict)

    def character_map(self) -> dict[str, ScriptCharacter]:
        return {character.name: character for character in self.characters}


def _validate_speed(value: str) -> None:
    if value == "自动":
        return
    if not SPEED_RE.match(value):
        raise ValueError(f"语速格式无效：{value}（应为 自动 或 x0.9）")
    speed = float(value[1:])
    if not 0.75 <= speed <= 1.5:
        raise ValueError(f"语速超出范围 x0.75..x1.5：{value}")


def _parse_overrides(value: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if not value:
        return overrides
    for token in re.split(r"[;；]", value):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"音色覆盖格式无效：{token}（应为 引擎=音色）")
        engine, voice = (part.strip() for part in token.split("=", 1))
        if engine not in {"qwen3tts", "edgetts"} or not voice:
            raise ValueError(f"音色覆盖无效：{token}")
        overrides[engine] = voice
    return overrides


def _format_overrides(overrides: dict[str, str]) -> str:
    return "; ".join(f"{engine}={voice}" for engine, voice in overrides.items())


def write_voicebook_script(script: VoicebookScript, output: Path) -> Path:
    meta: dict[str, Any] = {
        "格式": SCRIPT_FORMAT,
        "版本": SCRIPT_VERSION,
        "书名": script.title,
        "简介": script.description,
        "作者": script.author,
        "语言": script.language,
        "来源": script.source,
    }
    if script.cover:
        meta["封面"] = script.cover
    if script.protagonist_voices:
        meta["主角音"] = script.protagonist_voices
    meta.update(script.extra_meta)
    yaml_text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    lines = ["---", yaml_text, "---", "", "## 角色表", "# " + " | ".join(ROLE_COLUMNS)]
    for character in script.characters:
        _validate_speed(character.speed)
        values = (
            character.name,
            character.position,
            character.character_type,
            character.gender,
            character.age_group,
            character.region,
            character.voice_description,
            character.speed,
            _format_overrides(character.voice_overrides),
        )
        lines.append(
            " | ".join(value.replace("|", "／").replace("\n", " ") for value in values).rstrip()
        )
    lines.append("")
    for chapter in script.chapters:
        heading = f"## 章节 {chapter.number:04d} | {chapter.title}"
        if chapter.volume:
            heading += f"  # {chapter.volume}"
        lines.extend((heading, ""))
        for segment in chapter.segments:
            text = segment.text.replace("\r", "").replace("\n", " ").strip()
            if text:
                lines.append(f"[{segment.tag}] {text}")
        lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(output)
    return output


def _read_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("book.script 缺少 YAML front matter（首行应为 ---）")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise ValueError("book.script 的 YAML front matter 未闭合") from exc
    try:
        loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"book.script 的 YAML front matter 无效：{exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("book.script 的 YAML front matter 必须是对象")
    return loaded, "\n".join(lines[end + 1:])


def parse_voicebook_script(path: Path) -> VoicebookScript:
    meta, body = _read_front_matter(path.read_text(encoding="utf-8-sig"))
    if meta.get("格式") != SCRIPT_FORMAT:
        raise ValueError(f"不支持的脚本格式：{meta.get('格式')!r}")
    if meta.get("版本") != SCRIPT_VERSION:
        raise ValueError(f"不支持的脚本版本：{meta.get('版本')!r}")

    characters: list[ScriptCharacter] = []
    chapters: list[ScriptChapter] = []
    section = ""
    chapter_re = re.compile(r"^##\s+章节\s+(\d+)\s*\|\s*(.*?)(?:\s+#\s*(.+))?$")
    seen_names: set[str] = set()
    for line_number, raw in enumerate(body.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line == "## 角色表":
            section = "characters"
            continue
        chapter_match = chapter_re.match(line)
        if chapter_match:
            title = chapter_match.group(2).strip() or f"第{chapter_match.group(1)}章"
            chapters.append(ScriptChapter(int(chapter_match.group(1)), title, volume=chapter_match.group(3)))
            section = "chapter"
            continue
        if line.startswith("#"):
            continue
        if section == "characters":
            cols = [column.strip() for column in line.split("|")]
            if len(cols) != len(ROLE_COLUMNS):
                raise ValueError(f"角色表第 {line_number} 行应有 {len(ROLE_COLUMNS)} 列，实际 {len(cols)} 列")
            name, position, kind, gender, age, region, voice_desc, speed, overrides = cols
            if not name or name in seen_names:
                raise ValueError(f"角色名为空或重复：{name!r}")
            if position not in POSITIONS:
                raise ValueError(f"{name} 的定位无效：{position}")
            if kind not in CHARACTER_TYPES:
                raise ValueError(f"{name} 的类型无效：{kind}")
            if gender not in GENDERS:
                raise ValueError(f"{name} 的性别无效：{gender}")
            if age not in AGE_GROUPS:
                raise ValueError(f"{name} 的年龄段无效：{age}")
            _validate_speed(speed)
            characters.append(ScriptCharacter(name, position, kind, gender, age, region, voice_desc, speed, _parse_overrides(overrides)))
            seen_names.add(name)
            continue
        if section == "chapter":
            if not chapters:
                raise ValueError("正文出现在章节标题之前")
            match = TAG_RE.fullmatch(line)
            if not match or not match.group(1).strip():
                raise ValueError(f"章节正文第 {line_number} 行缺少显式标签：[旁白]/[角色]/[?]/[音]")
            tag, text = match.group(1).strip(), match.group(2).strip()
            if not text:
                continue
            base = tag.split("@", 1)[0]
            if base not in NARRATION_TAGS and base not in seen_names:
                raise ValueError(f"正文引用了角色表中不存在的角色：{base}")
            chapters[-1].segments.append(ScriptSegment(tag, text))
            continue
        raise ValueError(f"无法识别的脚本内容（第 {line_number} 行）：{line[:80]}")

    if not chapters:
        raise ValueError("book.script 没有章节")
    chapter_numbers = [chapter.number for chapter in chapters]
    if len(set(chapter_numbers)) != len(chapter_numbers) or chapter_numbers != sorted(chapter_numbers):
        raise ValueError("book.script 的章节编号必须唯一且递增")
    if not any(chapter.segments for chapter in chapters):
        raise ValueError("book.script 没有可合成正文")
    known = {"格式", "版本", "书名", "简介", "作者", "语言", "来源", "封面", "主角音"}
    protagonists = meta.get("主角音") or {}
    if not isinstance(protagonists, dict):
        raise ValueError("主角音必须是按引擎分组的映射")
    return VoicebookScript(
        title=str(meta.get("书名") or path.stem),
        description=str(meta.get("简介") or ""),
        author=str(meta.get("作者") or ""),
        language=str(meta.get("语言") or "zh-CN"),
        source=str(meta.get("来源") or ""),
        cover=str(meta.get("封面") or ""),
        protagonist_voices=protagonists,
        characters=characters,
        chapters=chapters,
        extra_meta={key: value for key, value in meta.items() if key not in known},
    )
