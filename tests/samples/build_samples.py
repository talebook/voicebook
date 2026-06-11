"""从 talebook 测试书库提取"对白+角色密集"选段，构建说话人识别测试语料

用法: uv run python tests/samples/build_samples.py [书库路径]
输出: tests/samples/<书名>.txt（带合成章节头，供 book2audio 直接使用）
"""

import html
import re
import sys
import zipfile
from pathlib import Path

LIBRARY = Path(sys.argv[1] if len(sys.argv) > 1 else
               "/Users/bytedance/github/talebook/tests/library")
OUT = Path(__file__).parent

SPEECH_VERBS = "说|道|喊|叫|骂|问|答|嚷|吼|叹"
QUOTE_RE = re.compile(r"[“「][^”」]{2,}[”」]")
NAME_VERB_RE = re.compile(rf"([一-龥]{{2,3}})(?:{SPEECH_VERBS})")

WINDOW, STRIDE, MAX_CHARS = 40, 10, 3500
SKIP_BOOKS = ("唐诗三百首", "麦肯锡方法", "鳄鱼怕怕", "test")
TITLE_MAP = {"Fan Ren Xiu Xian Zhi Xian Jie Pian": "凡人修仙之仙界篇", "Bai Nian Gu Du": "百年孤独"}
CHAPTER_LINE = re.compile(r"^\s*第[0-9一二三四五六七八九十百千零两]+章")


def epub_paragraphs(path: Path):
    """按文件序提取 epub 正文段落，返回 [(file_idx, [para,...])]"""
    z = zipfile.ZipFile(path)
    docs = sorted(n for n in z.namelist() if re.search(r"\.x?html?$", n.lower()))
    out = []
    for i, name in enumerate(docs):
        raw = z.read(name).decode("utf-8", "ignore")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        raw = re.sub(r"</?(p|br|div|h[1-6]|li|tr)[^>]*>", "\n", raw, flags=re.I)
        text = html.unescape(re.sub(r"<[^>]+>", "", raw))
        # 合并硬换行：不以句末标点结尾的行与下一行同段（部分epub把段落渲染成多行）
        merged, buf = [], ""
        for line in (s.strip() for s in text.splitlines()):
            if not line:
                continue
            buf += line
            if buf[-1] in "。！？”…：；」』":
                merged.append(buf)
                buf = ""
        if buf:
            merged.append(buf)
        # 去掉章节标题行（样本自带合成章节头，内部标题会干扰章节切分）和连续重复行
        paras, prev = [], None
        for p in merged:
            if p != prev and not CHAPTER_LINE.match(p):
                paras.append(p)
            prev = p
        if paras:
            out.append((i, paras))
    return out


def txt_paragraphs(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    return [(0, paras)]


def score_window(paras):
    text = "\n".join(paras)
    quotes = len(QUOTE_RE.findall(text))
    speakers = {m for m in NAME_VERB_RE.findall(text)}
    return quotes + 3 * len(speakers), quotes, len(speakers)


def best_passage(sections):
    best = (0, 0, 0, None)  # score, quotes, speakers, paras
    for _, paras in sections:
        for s in range(0, max(1, len(paras) - WINDOW), STRIDE):
            win = paras[s:s + WINDOW]
            score, quotes, speakers = score_window(win)
            if quotes >= 8 and score > best[0]:
                best = (score, quotes, speakers, win)
    return best


def main():
    books = {}
    for f in LIBRARY.rglob("*"):
        if f.suffix.lower() in (".epub", ".txt"):
            title = TITLE_MAP.get(f.stem.split(" - ")[0], f.stem.split(" - ")[0])
            if any(s in title for s in SKIP_BOOKS) or title in books:
                continue
            books[title] = f

    print(f"{'书名':　<10} {'格式':<5} {'引文':>4} {'说话人':>4}  样本")
    seen_content = set()
    for title, f in sorted(books.items()):
        sections = epub_paragraphs(f) if f.suffix.lower() == ".epub" else txt_paragraphs(f)
        score, quotes, speakers, win = best_passage(sections)
        if not win:
            print(f"{title:　<10} {f.suffix:<5}  -- 无对白密集段，跳过")
            continue
        text = "\n\n".join(win)
        if len(text) > MAX_CHARS:  # 截断到段落边界
            acc, kept = 0, []
            for p in win:
                if acc + len(p) > MAX_CHARS:
                    break
                kept.append(p)
                acc += len(p)
            text = "\n\n".join(kept)
            _, quotes, speakers = score_window(kept)
        if text[:200] in seen_content:  # 同书的拼音重复条目
            print(f"{title:　<10} {f.suffix:<5}  -- 内容重复，跳过")
            continue
        seen_content.add(text[:200])
        out = OUT / f"{title}.txt"
        out.write_text(f"第一章 {title}选段\n\n{text}\n", encoding="utf-8")
        print(f"{title:　<10} {f.suffix:<5} {quotes:>4} {speakers:>4}  {out.name} ({len(text)}字)")


if __name__ == "__main__":
    main()
