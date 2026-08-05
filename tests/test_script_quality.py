import hashlib
import unittest

from book2audio.script import ScriptChapter, ScriptSegment, VoicebookScript
from book2audio.script_quality import prepare_new_script


class ScriptQualityTests(unittest.TestCase):
    def _script(self, text, language="zh-CN"):
        locator = {
            "type": "epub-dom-text",
            "href": "OPS/chapter.xhtml",
            "dom_path": "html[1]/body[1]/p[1]",
            "start_char": 10,
            "end_char": 10 + len(text),
        }
        return VoicebookScript(
            title="测试书",
            language=language,
            chapters=[ScriptChapter(1, "第一章", [ScriptSegment("旁白", text, locator)], source_key="OPS/chapter.xhtml")],
        )

    def test_cjk_chunks_are_deterministic_bounded_and_keep_locator_ranges(self):
        text = "第一句很短。第二句也不长。" + "这是一个需要继续拆分的长句，" * 12 + "到这里结束。"
        first = self._script(text)
        second = self._script(text)

        first_report = prepare_new_script(first)
        second_report = prepare_new_script(second)
        first_rows = [(item.text, item.locator) for item in first.chapters[0].segments]
        second_rows = [(item.text, item.locator) for item in second.chapters[0].segments]

        self.assertEqual(first_rows, second_rows)
        self.assertEqual(text, "".join(item.text for item in first.chapters[0].segments))
        self.assertTrue(all(sum(not char.isspace() for char in item.text) <= 80 for item in first.chapters[0].segments))
        self.assertEqual(10, first.chapters[0].segments[0].locator["start_char"])
        self.assertEqual(10 + len(text), first.chapters[0].segments[-1].locator["end_char"])
        for item in first.chapters[0].segments:
            expected = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
            self.assertEqual(expected, item.locator["text_sha256"])
        self.assertEqual(first_report, second_report)
        self.assertGreater(first_report["segments_after"], first_report["segments_before"])

    def test_english_chunks_use_word_budget_without_cutting_words(self):
        words = [f"word{index}" for index in range(95)]
        text = " ".join(words[:48]) + ". " + " ".join(words[48:]) + "."
        script = self._script(text, language="en")

        prepare_new_script(script)
        chunks = [item.text for item in script.chapters[0].segments]

        self.assertTrue(all(len(chunk.split()) <= 40 for chunk in chunks))
        self.assertEqual(words, " ".join(chunks).replace(".", "").split())

    def test_unmapped_locator_is_reported_but_preserved(self):
        text = "短句。" * 40
        script = VoicebookScript(
            title="测试书",
            chapters=[ScriptChapter(1, "第一章", [ScriptSegment("旁白", text, {"href": "chapter.xhtml"})])],
        )

        report = prepare_new_script(script)

        self.assertGreater(len(script.chapters[0].segments), 1)
        self.assertTrue(all(item.locator == {"href": "chapter.xhtml"} for item in script.chapters[0].segments))
        self.assertEqual(len(script.chapters[0].segments), report["locator_unmapped_count"])

    def test_leading_whitespace_keeps_locator_offsets_relative_to_source_text(self):
        text = "  第一段很短。第二段也很短。"
        script = self._script(text)

        prepare_new_script(script)

        first = script.chapters[0].segments[0]
        self.assertEqual("第一段很短。第二段也很短。", first.text)
        self.assertEqual(12, first.locator["start_char"])
        self.assertEqual(10 + len(text), first.locator["end_char"])


if __name__ == "__main__":
    unittest.main()
