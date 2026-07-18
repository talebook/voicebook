#!/usr/bin/env python3
"""从维基文库下载三部公版小说的前两回，生成可复现的 TXT 输入。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


API = "https://zh.wikisource.org/w/api.php"
ROOT = Path(__file__).resolve().parent
BOOKS = (
    {
        "id": "xiyouji",
        "title": "西遊記",
        "author": "吳承恩",
        "description": "明代神魔長篇小說；以石猴出世與求道開篇。",
        "chapters": (
            ("第一回 靈根育孕源流出 心性修持大道生", "西遊記/第001回"),
            ("第二回 悟徹菩提真妙理 斷魔歸本合元神", "西遊記/第002回"),
        ),
    },
    {
        "id": "rulinwaishi",
        "title": "儒林外史",
        "author": "吳敬梓",
        "description": "清代諷刺長篇小說；前兩回由王冕引出科舉與士林眾生。",
        "chapters": (
            ("第一回 說楔子敷陳大義 借名流隱括全文", "儒林外史/第01回"),
            ("第二回 王孝廉村學識同科 周蒙師暮年登上第", "儒林外史/第02回"),
        ),
    },
    {
        "id": "hongloumeng",
        "title": "紅樓夢",
        "author": "曹雪芹",
        "description": "清代章回長篇小說；前兩回交代石頭記緣起與賈府人物脈絡。",
        "chapters": (
            ("第一回 甄士隱夢幻識通靈 賈雨村風塵懷閨秀", "紅樓夢/第001回"),
            ("第二回 賈夫人仙逝揚州城 冷子興演說榮國府", "紅樓夢/第002回"),
        ),
    },
)


def fetch(page: str) -> str:
    response = requests.get(
        API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": page,
            "format": "json",
            "formatversion": 2,
        },
        headers={"User-Agent": "voicebook-tool-evaluation/0.2 (https://github.com/talebook/voicebook)"},
        timeout=30,
    )
    response.raise_for_status()
    page_data = response.json()["query"]["pages"][0]
    if page_data.get("missing"):
        raise RuntimeError(f"維基文庫頁面不存在：{page}")
    extract = page_data.get("extract", "").strip()
    if not extract:
        raise RuntimeError(f"維基文庫頁面沒有正文：{page}")
    return extract


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--measure", action="store_true", help="只打印各章字符数，不写文件")
    args = parser.parse_args()
    records = []
    for book in BOOKS:
        sections = []
        for heading, page in book["chapters"]:
            text = fetch(page)
            print(f"{book['title']} / {heading}: {len(text):,} 字符")
            sections.append((heading, text))
            records.append({
                "书名": book["title"],
                "章节": heading,
                "字符数": len(text),
                "页面": page,
                "来源": f"https://zh.wikisource.org/wiki/{page}",
            })
        if args.measure:
            continue
        source = [
            f"《{book['title']}》",
            f"作者：{book['author']}",
            f"内容简介：{book['description']}",
            "",
        ]
        for heading, text in sections:
            source.extend((heading, text, ""))
        (ROOT / f"{book['id']}.txt").write_text("\n".join(source), encoding="utf-8")
    if not args.measure:
        (ROOT / "sources.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
