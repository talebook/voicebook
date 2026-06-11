"""识别结果导出为 Markdown 报告（不做TTS）：角色表 + 逐段说话人标注"""

from pathlib import Path
from typing import Dict, List

from .parser import Chapter


def write_report(book_name: str, chapters: List[Chapter], quotes_by_ch: Dict,
                 profiles: Dict, voices: Dict, output: Path):
    lines = [f"# {book_name} 识别报告", "",
             f"章节：{chapters[0].title} ～ {chapters[-1].title}（共{len(chapters)}章）", "",
             "## 角色表", "",
             "| 角色 | 性别 | 年龄 | 音色 | 依据 |",
             "|------|------|------|------|------|"]
    for n in sorted(profiles):
        p = profiles[n]
        v, rate, pitch = voices[n]
        age = f"{p.age}岁/{p.age_stage}" if p.age else p.age_stage
        ev = p.evidence[0].replace("|", "丨") if p.evidence else "-"
        lines.append(f"| {n} | {p.gender} | {age} | {v.replace('zh-CN-', '')} {pitch} | {ev} |")
    lines.append("")

    method_label = {"R1": "规则·后随", "R1b": "规则·后随主语", "R2": "规则·前导",
                    "R3": "规则·邻段", "R4": "规则·轮替", "R5": "规则·冒号引导",
                    "R6": "规则·呼唤前瞻", "CSI": "模型", "sfx": "拟声", "unknown": "未识别"}
    for ch in chapters:
        lines += [f"## {ch.title}", ""]
        quotes = quotes_by_ch[ch.num]
        by_para = {}
        for q in quotes:
            by_para.setdefault(q.para_idx, []).append(q)
        paras = [p.strip() for p in ch.content.splitlines() if p.strip()]
        for pi, para in enumerate(paras):
            pq = sorted(by_para.get(pi, []), key=lambda x: x.span[0])
            if not pq:
                lines += [f"> {para}", ""]
                continue
            pos = 0
            for q in pq:
                if para[pos:q.span[0]].strip():
                    lines += [f"> {para[pos:q.span[0]].strip()}", ""]
                tag = method_label.get(q.method, q.method)
                if q.kind == "sfx":
                    lines += [f"🔊 *{q.text}*（拟声）", ""]
                else:
                    lines += [f"**{q.speaker or '？？'}**（{tag}）：“{q.text}”", ""]
                pos = q.span[1]
            if para[pos:].strip():
                lines += [f"> {para[pos:].strip()}", ""]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
