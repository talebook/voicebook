import tempfile
import unittest
import zipfile
from pathlib import Path

from book2audio.books import parse_chapter_selection, read_epub, read_txt, split_txt_chapters


class TxtBookTests(unittest.TestCase):
    def test_rich_headings_volume_special_and_metadata(self):
        text = """《山海录》
作者：某人
内容简介：一场远行。

第一卷 入山
序章 风起
这是序章。
第一章 初见
这是正文。
第2回 夜谈
“你是谁？”少年问道。
番外一 归途
这是番外。
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.txt"
            path.write_text(text, encoding="utf-8")
            book = read_txt(path)

        self.assertEqual(("山海录", "某人", "一场远行。"), (book.title, book.author, book.description))
        self.assertEqual(["序章 风起", "第一章 初见", "第2回 夜谈", "番外一 归途"], [chapter.title for chapter in book.chapters])
        self.assertTrue(all(chapter.volume == "第一卷 入山" for chapter in book.chapters))

    def test_directive_and_no_heading_fallback(self):
        chapters, _ = split_txt_chapters("#@chapter: 自定义\n正文")
        self.assertEqual(("自定义", "正文"), (chapters[0].title, chapters[0].content))
        chapters, _ = split_txt_chapters("只有一段正文。")
        self.assertEqual(("正文", "只有一段正文。"), (chapters[0].title, chapters[0].content))

    def test_hard_wrapped_lines_are_joined_but_paragraph_boundaries_remain(self):
        chapters, _ = split_txt_chapters("第一章\n这是被排版切断的\n同一句话。\n　　这是新段。")
        self.assertEqual("这是被排版切断的同一句话。\n这是新段。", chapters[0].content)

    def test_chapter_selection(self):
        self.assertEqual([1, 3, 8, 9, 10, 11, 12], parse_chapter_selection("1,3,8-12", 12))
        with self.assertRaisesRegex(ValueError, "越界"):
            parse_chapter_selection("13", 12)


class EpubBookTests(unittest.TestCase):
    def test_minimal_epub_spine_metadata_and_cover(self):
        container = """<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>"""
        opf = """<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>测试书</dc:title><dc:creator>作者甲</dc:creator><dc:language>zh-CN</dc:language></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/><item id="extra" href="extra.xhtml" media-type="application/xhtml+xml"/><item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/></manifest><spine><itemref idref="nav"/><itemref idref="ch1"/><itemref idref="extra" linear="no"/></spine></package>"""
        html = "<html><body><h1>第一章 开始</h1><p>第一段。</p><h2>第二章 继续</h2><p>第二段。</p></body></html>"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("META-INF/container.xml", container)
                archive.writestr("OPS/content.opf", opf)
                archive.writestr("OPS/nav.xhtml", "<html><body><p>目录不应进入正文</p></body></html>")
                archive.writestr("OPS/ch1.xhtml", html)
                archive.writestr("OPS/extra.xhtml", "<html><body><p>非线性附录不应进入正文</p></body></html>")
                archive.writestr("OPS/cover.jpg", b"fake-cover")
            book = read_epub(path)

        self.assertEqual(("测试书", "作者甲"), (book.title, book.author))
        self.assertEqual(["第一章 开始", "第二章 继续"], [chapter.title for chapter in book.chapters])
        self.assertEqual(b"fake-cover", book.cover_data)


if __name__ == "__main__":
    unittest.main()
