#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from pathlib import Path

from book2audio.books import read_book
from book2audio.script import parse_voicebook_script
from book2audio.tool_pipeline import inspect_book


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*")
TECHNICAL_TITLE = re.compile(
    r"^(?:titlepage|cover(?:page)?|index(?:_split)?[_-]?\d+|chapter[_-]?\d+|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.I,
)
STYLESHEET = re.compile(
    r"^(?:html|body|p|div|h[1-6]|\.[\w-]+|#[\w-]+)(?:\s+[^{}]+)?\s*\{[^{}]*(?:margin|padding|font|color|display|width|height)\s*:[^{}]*\}\s*$",
    re.I,
)


def mode(text: str) -> str:
    visible = [char for char in text if not char.isspace()]
    cjk = sum(bool(CJK_RE.fullmatch(char)) for char in visible)
    return "cjk" if cjk and cjk / max(1, len(visible)) >= 0.2 else "words"


def units(text: str, kind: str) -> int:
    return sum(not char.isspace() for char in text) if kind == "cjk" else len(WORD_RE.findall(text))


def evaluate(book_path: Path, chapter_limit: int) -> dict[str, object]:
    started = time.monotonic()
    book = read_book(book_path)
    selected_count = min(chapter_limit, len(book.chapters))
    selection = f"1-{selected_count}"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script_path = root / "book.script"
        first = inspect_book(book_path, script_path, chapters=selection)
        locator_path = script_path.with_name(f"{script_path.name}.locators.json")
        first_script = script_path.read_bytes()
        first_locator = locator_path.read_bytes()
        inspect_book(book_path, script_path, chapters=selection)
        parsed = parse_voicebook_script(script_path)
        script_deterministic = first_script == script_path.read_bytes()
        locator_deterministic = first_locator == locator_path.read_bytes()
        locator_payload = json.loads(locator_path.read_text(encoding="utf-8"))

    segments = [segment for chapter in parsed.chapters for segment in chapter.segments]
    cjk_lengths = [units(item.text, "cjk") for item in segments if mode(item.text) == "cjk"]
    word_lengths = [units(item.text, "words") for item in segments if mode(item.text) == "words"]
    locator_entries = locator_payload.get("segments", [])
    locator_keys = [
        (item.get("chapter_number"), item.get("segment_sha256"), item.get("occurrence"))
        for item in locator_entries
    ]
    invalid_ranges = sum(
        1
        for item in locator_entries
        if not isinstance(item.get("locator"), dict)
        or not isinstance(item["locator"].get("start_char"), int)
        or not isinstance(item["locator"].get("end_char"), int)
        or item["locator"]["start_char"] > item["locator"]["end_char"]
    )
    return {
        "file": book_path.name,
        "title": parsed.title,
        "language": parsed.language,
        "full_chapters": len(book.chapters),
        "inspected_chapters": len(parsed.chapters),
        "segments": len(segments),
        "technical_titles": [chapter.title for chapter in book.chapters if TECHNICAL_TITLE.fullmatch(chapter.title)],
        "unnamed_title_count": sum(chapter.title.startswith("未命名章节 ") for chapter in book.chapters),
        "stylesheet_block_count": sum(
            bool(STYLESHEET.fullmatch(line.strip()))
            for chapter in book.chapters
            for line in chapter.content.splitlines()
        ),
        "max_cjk_chars": max(cjk_lengths, default=0),
        "max_english_words": max(word_lengths, default=0),
        "script_deterministic": script_deterministic,
        "locator_deterministic": locator_deterministic,
        "locator_key_unique": len(locator_keys) == len(set(locator_keys)),
        "invalid_locator_range_count": invalid_ranges,
        "quality_report": first.quality_report,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("books", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chapter-limit", type=int, default=5)
    args = parser.parse_args()
    result = {"books": [evaluate(path.expanduser().resolve(), args.chapter_limit) for path in args.books]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
