"""EPUB/TXT 输入解析与统一的书籍文档模型。"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable
from xml.etree import ElementTree as ET


MAX_EPUB_FILES = 10_000
MAX_EPUB_MEMBER_BYTES = 64 * 1024 * 1024
MAX_EPUB_TOTAL_BYTES = 512 * 1024 * 1024
MAX_HEADING_CHARS = 80


@dataclass
class BookParagraph:
    text: str
    locator: dict[str, object] = field(default_factory=dict)


@dataclass
class BookChapter:
    number: int
    title: str
    content: str
    volume: str | None = None
    source_key: str = ""
    paragraphs: list[BookParagraph] = field(default_factory=list)


@dataclass
class BookDocument:
    title: str
    author: str = ""
    description: str = ""
    language: str = "zh-CN"
    source: str = ""
    chapters: list[BookChapter] = field(default_factory=list)
    cover_data: bytes | None = None
    cover_suffix: str = ".jpg"
    warnings: list[str] = field(default_factory=list)


class _HTMLTextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "blockquote", "h1", "h2", "h3", "h4"}
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self._heading: list[str] | None = None
        self._heading_start = 0
        self.blocks: list[tuple[str, str, str, str]] = []
        self._stack: list[tuple[str, str]] = []
        self._sibling_counts: list[dict[str, int]] = [{}]
        self._captures: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        counts = self._sibling_counts[-1]
        counts[tag] = counts.get(tag, 0) + 1
        path = "/".join([item[1] for item in self._stack] + [f"{tag}[{counts[tag]}]"])
        attributes = dict(attrs)
        if tag not in self.VOID_TAGS:
            self._stack.append((tag, f"{tag}[{counts[tag]}]"))
            self._sibling_counts.append({})
        if tag not in self.VOID_TAGS and tag in {"p", "li", "blockquote", "h1", "h2", "h3", "h4"}:
            self._captures.append({"tag": tag, "id": attributes.get("id", ""), "path": path, "parts": []})
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = []
            self._heading_start = len("".join(self.parts))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag in self.VOID_TAGS:
            return
        if tag in {"h1", "h2", "h3", "h4"} and self._heading is not None:
            title = _clean_line("".join(self._heading))
            if title:
                self.headings.append((self._heading_start, title))
            self._heading = None
        if self._captures and self._captures[-1]["tag"] == tag:
            capture = self._captures.pop()
            text = _clean_line("".join(capture["parts"]))
            if text:
                self.blocks.append((tag, text, str(capture["id"]), str(capture["path"])))
        if self._stack:
            while self._stack:
                opened, _ = self._stack.pop()
                self._sibling_counts.pop()
                if opened == tag:
                    break

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        for capture in self._captures:
            capture["parts"].append(data)
        if self._heading is not None:
            self._heading.append(data)

    def text(self) -> str:
        raw = html.unescape("".join(self.parts)).replace("\xa0", " ")
        lines = [_clean_line(line) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _clean_line(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError("TXT 编码无法识别：仅支持 UTF-8/UTF-8 BOM/GB18030")


NUM = r"[0-9０-９一二三四五六七八九十百千万零〇两壹贰叁肆伍陆柒捌玖拾佰仟]+"
VOLUME_RE = re.compile(
    rf"^(?:第\s*{NUM}\s*(?:卷|部|篇)|(?:上|中|下|前|后|终)\s*(?:卷|部|篇)|卷\s*{NUM})(?:[　 :：·、-]*.{{0,50}})?$",
    re.I,
)
CHAPTER_RE = re.compile(
    rf"^(?:第\s*{NUM}\s*(?:章|节|回|幕|集)|(?:章|节|回)\s*{NUM})(?:[　 :：·、-]*.{{0,55}})?$",
    re.I,
)
COMBINED_RE = re.compile(
    rf"^(?:第\s*{NUM}\s*(?:卷|部|篇).{{0,35}}?第\s*{NUM}\s*(?:章|节|回|幕|集))(?:[　 :：·、-]*.{{0,35}})?$",
    re.I,
)
SPECIAL_RE = re.compile(
    r"^(?:序章|序幕|楔子|引子|前言|尾声|终章|后记|番外(?:篇|章)?(?:[一二三四五六七八九十\d]+)?|大结局)(?:[　 :：·、-]*.{0,50})?$",
    re.I,
)
ENGLISH_CHAPTER_RE = re.compile(r"^chapter\s+[0-9ivxlcdm]+(?:\s*[:.\-]\s*.{0,50})?$", re.I)
DIRECTIVE_RE = re.compile(r"^#@(?P<kind>chapter|section)\s*:\s*(?P<title>.+)$", re.I)
BAD_HEADING_PUNCTUATION = re.compile(r"[。！？!?；;，,]$")


def _heading_kind(line: str) -> str | None:
    stripped = _clean_line(line)
    if not stripped or len(stripped) > MAX_HEADING_CHARS:
        return None
    directive = DIRECTIVE_RE.match(stripped)
    if directive:
        return "chapter"
    if BAD_HEADING_PUNCTUATION.search(stripped):
        return None
    if COMBINED_RE.match(stripped):
        return "combined"
    if VOLUME_RE.match(stripped):
        return "volume"
    if CHAPTER_RE.match(stripped) or SPECIAL_RE.match(stripped) or ENGLISH_CHAPTER_RE.match(stripped):
        return "chapter"
    return None


def _normalize_txt_body(lines: Iterable[str]) -> str:
    """合并排版产生的硬换行，同时保留显式缩进/句末形成的自然段。"""
    paragraphs: list[str] = []
    current = ""
    sentence_end = re.compile(r"[。！？!?…；;：:）)】\]》〉」』”’]$")
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        explicitly_indented = raw.startswith(("　　", "  ", "\t"))
        if current and (explicitly_indented or sentence_end.search(current)):
            paragraphs.append(current)
            current = stripped
        elif current:
            current += stripped
        else:
            current = stripped
    if current:
        paragraphs.append(current)
    return "\n".join(paragraphs).strip()


def _paragraphs_from_text(content: str, *, locator_type: str = "text-segment") -> list[BookParagraph]:
    return [
        BookParagraph(
            text=paragraph,
            locator={"type": locator_type, "paragraph_index": index},
        )
        for index, paragraph in enumerate(content.splitlines())
        if paragraph.strip()
    ]


def split_txt_chapters(text: str) -> tuple[list[BookChapter], list[str]]:
    """识别常见网文目录格式；没有标题时将全文作为一章。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    markers: list[tuple[int, str, str]] = []
    for index, raw in enumerate(lines):
        kind = _heading_kind(raw)
        if kind:
            title = _clean_line(raw)
            match = DIRECTIVE_RE.match(title)
            if match:
                title = match.group("title").strip()
            markers.append((index, kind, title))

    warnings: list[str] = []
    if not any(kind in {"chapter", "combined"} for _, kind, _ in markers):
        content = _normalize_txt_body(lines)
        return (
            [BookChapter(1, "正文", content, paragraphs=_paragraphs_from_text(content))] if content else []
        ), warnings

    chapters: list[BookChapter] = []
    volume: str | None = None
    chapter_markers = [(i, k, t) for i, k, t in markers if k in {"chapter", "combined", "volume"}]
    for position, (line_index, kind, title) in enumerate(chapter_markers):
        if kind == "volume":
            volume = title
            continue
        next_line = len(lines)
        for next_index, next_kind, _ in chapter_markers[position + 1:]:
            if next_kind in {"chapter", "combined", "volume"}:
                next_line = next_index
                break
        body = _normalize_txt_body(lines[line_index + 1:next_line])
        if not body:
            warnings.append(f"忽略空章节：{title}")
            continue
        if kind == "combined":
            volume = re.split(r"(?=第\s*" + NUM + r"\s*(?:章|节|回|幕|集))", title, maxsplit=1)[0].strip() or volume
        chapters.append(
            BookChapter(
                len(chapters) + 1,
                title,
                body,
                volume,
                paragraphs=_paragraphs_from_text(body),
            )
        )

    if len(chapters) > max(20, len(lines) // 4):
        warnings.append("章节标题密度异常，请检查 TXT 是否把正文误识别成标题")
    arabic_ordinals = []
    for chapter in chapters:
        match = re.match(r"^第\s*(\d+)\s*(?:章|节|回|幕|集)", chapter.title)
        if match:
            arabic_ordinals.append(int(match.group(1)))
    if any(right <= left or right - left > 20 for left, right in zip(arabic_ordinals, arabic_ordinals[1:])):
        warnings.append("章节序号存在倒退、重复或大幅跳号，请检查目录识别结果")
    return chapters, warnings


def _txt_metadata(text: str, fallback: str) -> tuple[str, str, str]:
    first = [_clean_line(line) for line in text.splitlines()[:80] if _clean_line(line)]
    title = fallback
    author = ""
    description = ""
    for line in first:
        match = re.match(r"^#title\s*:\s*(.+)$", line, re.I)
        if match:
            title = match.group(1).strip()
        match = re.match(r"^[《<]{1,2}(.+?)[》>]{1,2}$", line)
        if match and len(match.group(1)) <= 80:
            title = match.group(1).strip()
        match = re.match(r"^作者\s*[:：]\s*(.+)$", line)
        if match:
            author = match.group(1).strip()
        match = re.match(r"^(?:内容)?简介\s*[:：]\s*(.+)$", line)
        if match:
            description = match.group(1).strip()
    return title, author, description


def read_txt(path: Path) -> BookDocument:
    text, encoding = _decode_text(path.read_bytes())
    title, author, description = _txt_metadata(text, path.stem)
    chapters, warnings = split_txt_chapters(text)
    if encoding == "gb18030":
        warnings.append("TXT 使用 GB18030 编码读取")
    if not chapters:
        raise ValueError("TXT 没有可用正文")
    return BookDocument(title, author, description, source=path.name, chapters=chapters, warnings=warnings)


def _safe_epub_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_EPUB_FILES:
        raise ValueError(f"EPUB 文件数量超过限制（{MAX_EPUB_FILES}）")
    if sum(info.file_size for info in infos) > MAX_EPUB_TOTAL_BYTES:
        raise ValueError("EPUB 解压后总体积超过 512 MiB")
    members: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        normalized = PurePosixPath(info.filename)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"EPUB 包含不安全路径：{info.filename}")
        if info.file_size > MAX_EPUB_MEMBER_BYTES:
            raise ValueError(f"EPUB 单文件超过 64 MiB：{info.filename}")
        members[str(normalized)] = info
    return members


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(root: ET.Element, local_name: str) -> str:
    for node in root.iter():
        if _local_name(node.tag) == local_name and node.text:
            return node.text.strip()
    return ""


def _resolve(base: str, href: str) -> str:
    return str(PurePosixPath(base).joinpath(href))


def _epub_sections(raw_html: bytes, fallback_title: str, href: str) -> list[tuple[str, str, str, list[BookParagraph]]]:
    parser = _HTMLTextExtractor()
    parser.feed(raw_html.decode("utf-8", errors="replace"))
    text = parser.text()
    if not text:
        return []
    lines = text.splitlines()
    indices = [(i, line) for i, line in enumerate(lines) if _heading_kind(line) in {"chapter", "combined"}]
    if len(indices) <= 1:
        title = indices[0][1] if indices else (parser.headings[0][1] if parser.headings else fallback_title)
        if indices and indices[0][0] == 0:
            text = "\n".join(lines[1:]).strip()
        paragraphs = []
        for tag, block_text, element_id, dom_path in parser.blocks:
            if tag.startswith("h") and block_text == title:
                continue
            paragraphs.append(
                BookParagraph(
                    block_text,
                    {
                        "type": "epub-dom-text",
                        "href": href,
                        "element_id": element_id,
                        "dom_path": dom_path,
                    },
                )
            )
        if not paragraphs:
            paragraphs = _paragraphs_from_text(text, locator_type="epub-text")
            for paragraph in paragraphs:
                paragraph.locator["href"] = href
        content = "\n".join(paragraph.text for paragraph in paragraphs)
        source_key = f"{href}#{parser.blocks[0][2] or fallback_title}" if parser.blocks else href
        return [(title, content, source_key, paragraphs)] if content else []
    sections: list[tuple[str, str, str, list[BookParagraph]]] = []
    block_headings = [
        (index, block)
        for index, block in enumerate(parser.blocks)
        if block[0].startswith("h") and _heading_kind(block[1]) in {"chapter", "combined"}
    ]
    if len(block_headings) == len(indices):
        for pos, (index, heading) in enumerate(block_headings):
            end = block_headings[pos + 1][0] if pos + 1 < len(block_headings) else len(parser.blocks)
            paragraphs = [
                BookParagraph(
                    block_text,
                    {
                        "type": "epub-dom-text",
                        "href": href,
                        "element_id": element_id,
                        "dom_path": dom_path,
                    },
                )
                for tag, block_text, element_id, dom_path in parser.blocks[index + 1:end]
                if not tag.startswith("h")
            ]
            body = "\n".join(paragraph.text for paragraph in paragraphs).strip()
            if body:
                anchor = heading[2] or f"chapter-{pos + 1}"
                sections.append((heading[1], body, f"{href}#{anchor}", paragraphs))
        return sections
    for pos, (index, title) in enumerate(indices):
        end = indices[pos + 1][0] if pos + 1 < len(indices) else len(lines)
        body = "\n".join(lines[index + 1:end]).strip()
        if body:
            paragraphs = _paragraphs_from_text(body, locator_type="epub-text")
            for paragraph in paragraphs:
                paragraph.locator["href"] = href
            sections.append((title, body, f"{href}#chapter-{pos + 1}", paragraphs))
    return sections


def read_epub(path: Path) -> BookDocument:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("不是有效的 EPUB/ZIP 文件") from exc
    with archive:
        members = _safe_epub_members(archive)
        container_name = "META-INF/container.xml"
        if container_name not in members:
            raise ValueError("EPUB 缺少 META-INF/container.xml")
        container = ET.fromstring(archive.read(container_name))
        rootfile = next((n.attrib.get("full-path") for n in container.iter() if _local_name(n.tag) == "rootfile"), None)
        if not rootfile or rootfile not in members:
            raise ValueError("EPUB 找不到 OPF package")
        opf = ET.fromstring(archive.read(rootfile))
        opf_dir = str(PurePosixPath(rootfile).parent)
        if opf_dir == ".":
            opf_dir = ""
        title = _first_text(opf, "title") or path.stem
        author = _first_text(opf, "creator")
        description = _first_text(opf, "description")
        language = _first_text(opf, "language") or "zh-CN"

        manifest: dict[str, tuple[str, str, str]] = {}
        cover_id = ""
        for node in opf.iter():
            name = _local_name(node.tag)
            if name == "item":
                manifest[node.attrib.get("id", "")] = (
                    node.attrib.get("href", ""), node.attrib.get("media-type", ""), node.attrib.get("properties", "")
                )
            elif name == "meta" and node.attrib.get("name") == "cover":
                cover_id = node.attrib.get("content", "")
        spine = [
            (node.attrib.get("idref", ""), node.attrib.get("linear", "yes").lower())
            for node in opf.iter() if _local_name(node.tag) == "itemref"
        ]

        cover_item = next((item for item in manifest.values() if "cover-image" in item[2]), None)
        if cover_item is None and cover_id:
            cover_item = manifest.get(cover_id)
        cover_data = None
        cover_suffix = ".jpg"
        if cover_item:
            cover_path = _resolve(opf_dir, cover_item[0])
            if cover_path in members:
                cover_data = archive.read(cover_path)
                cover_suffix = Path(cover_item[0]).suffix.lower() or ".jpg"

        chapters: list[BookChapter] = []
        for idref, linear in spine:
            item = manifest.get(idref)
            if (
                not item
                or linear == "no"
                or item[1] not in {"application/xhtml+xml", "text/html"}
                or "nav" in item[2].split()
            ):
                continue
            item_path = _resolve(opf_dir, item[0])
            if item_path not in members:
                continue
            fallback = Path(item[0]).stem
            for section_title, content, source_key, paragraphs in _epub_sections(
                archive.read(item_path), fallback, item_path
            ):
                chapters.append(
                    BookChapter(
                        len(chapters) + 1,
                        section_title,
                        content,
                        source_key=source_key,
                        paragraphs=paragraphs,
                    )
                )
        if not chapters:
            raise ValueError("EPUB spine 中没有可用正文")
        return BookDocument(
            title=title,
            author=author,
            description=description,
            language=language,
            source=path.name,
            chapters=chapters,
            cover_data=cover_data,
            cover_suffix=cover_suffix,
        )


def read_book(path: Path) -> BookDocument:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"输入文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return read_txt(path)
    if suffix == ".epub":
        return read_epub(path)
    raise ValueError("仅支持 .epub 和 .txt 输入")


def parse_chapter_selection(expression: str | None, total: int) -> list[int]:
    if total < 1:
        return []
    if not expression:
        return list(range(1, total + 1))
    selected: set[int] = set()
    for token in expression.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"无效章节范围：{token}")
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"章节范围起点大于终点：{token}")
            selected.update(range(start, end + 1))
        elif token.isdigit():
            selected.add(int(token))
        else:
            raise ValueError(f"无效章节编号：{token}")
    invalid = sorted(number for number in selected if number < 1 or number > total)
    if invalid:
        raise ValueError(f"章节编号越界（全书共 {total} 章）：{','.join(map(str, invalid))}")
    if not selected:
        raise ValueError("章节选择不能为空")
    return sorted(selected)


def selected_chapters(chapters: Iterable[BookChapter], numbers: Iterable[int]) -> list[BookChapter]:
    wanted = set(numbers)
    return [chapter for chapter in chapters if chapter.number in wanted]
