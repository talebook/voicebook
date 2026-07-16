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
from pathlib import Path
from typing import Dict, List, Tuple

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
