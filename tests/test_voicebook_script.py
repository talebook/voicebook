import tempfile
import unittest
from pathlib import Path

from book2audio.script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    parse_voicebook_script,
    write_voicebook_script,
)


class VoicebookScriptTests(unittest.TestCase):
    def test_chinese_front_matter_and_role_table_round_trip(self):
        value = VoicebookScript(
            title="凡人修仙传",
            author="忘语",
            source="book.epub",
            cover="book.cover.jpg",
            protagonist_voices={"qwen3tts": {"男": "Andre", "女": "Serena"}},
            characters=[
                ScriptCharacter("旁白", "旁白", gender="男", age_group="中年", speed="x1.0"),
                ScriptCharacter("韩立", "主角", "人类", "男", "青年", "山区", "低沉、克制", "x1.05", {"qwen3tts": "Andre"}),
                ScriptCharacter("机械守卫", "配角", "机器人", "中性", "未知", "未知", "冷硬", "x0.9"),
            ],
            chapters=[ScriptChapter(1, "第一章", [ScriptSegment("旁白", "夜深了。"), ScriptSegment("韩立@低语", "走吧。"), ScriptSegment("?", "谁？")])],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.script"
            write_voicebook_script(value, path)
            parsed = parse_voicebook_script(path)
            raw = path.read_text(encoding="utf-8")

        self.assertTrue(raw.startswith("---\n格式: voicebook-script"))
        self.assertIn("## 章节 0001 | 第一章", raw)
        self.assertFalse(any(line.endswith((" ", "\t")) for line in raw.splitlines()))
        self.assertEqual(value, parsed)

    def test_rejects_unknown_role_and_invalid_speed(self):
        raw = """---
格式: voicebook-script
版本: 1
书名: 测试
---
## 角色表
# 角色 | 定位 | 类型 | 性别 | 年龄段 | 地域 | 音色描述 | 语速 | 音色覆盖
旁白 | 旁白 | 人类 | 男 | 中年 | 中原 | 沉稳 | x1.0 |
## 章节 0001 | 开始
[不存在] 你好
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.script"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不存在"):
                parse_voicebook_script(path)

    def test_locator_sidecar_round_trip_uses_text_fingerprint(self):
        locator = {
            "type": "epub-dom-text",
            "href": "OPS/ch1.xhtml",
            "element_id": "p1",
            "dom_path": "html[1]/body[1]/p[1]",
            "start_char": 0,
            "end_char": 4,
        }
        value = VoicebookScript(
            title="定位测试",
            characters=[ScriptCharacter("旁白", "旁白", gender="男")],
            chapters=[
                ScriptChapter(
                    1,
                    "开始",
                    [ScriptSegment("旁白", "天亮了。", locator)],
                    source_key="OPS/ch1.xhtml#start",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.script"
            write_voicebook_script(value, path)
            parsed = parse_voicebook_script(path)

            self.assertTrue((Path(directory) / "book.script.locators.json").is_file())
            self.assertEqual(locator, parsed.chapters[0].segments[0].locator)
            self.assertEqual("OPS/ch1.xhtml#start", parsed.chapters[0].source_key)


if __name__ == "__main__":
    unittest.main()
