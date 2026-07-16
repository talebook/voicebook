import unittest

from book2audio.script import ScriptChapter, ScriptCharacter, ScriptSegment
from book2audio.voice_casting import QWEN_VOICES, adjacency_graph, assign_cast


class VoiceCastingTests(unittest.TestCase):
    def test_catalog_has_49_unique_voices(self):
        self.assertEqual(49, len(QWEN_VOICES))
        self.assertEqual(49, len({voice.voice_id for voice in QWEN_VOICES}))

    def test_reserved_leads_nonhuman_dialect_and_adjacency(self):
        characters = [
            ScriptCharacter("旁白", "旁白", gender="男", age_group="中年"),
            ScriptCharacter("男主", "主角", gender="男", age_group="青年"),
            ScriptCharacter("甲", gender="男", age_group="青年"),
            ScriptCharacter("乙", gender="男", age_group="青年"),
            ScriptCharacter("机械守卫", character_type="机器人", gender="男", age_group="成年", voice_description="冷硬"),
        ]
        chapters = [ScriptChapter(1, "开始", [
            ScriptSegment("甲", "一"), ScriptSegment("旁白", "他说。"), ScriptSegment("乙", "二"),
        ])]
        cast = assign_cast(characters, chapters, "qwen3tts", {"男": "Andre", "女": "Serena"})

        self.assertEqual("Andre", cast["男主"].voice)
        self.assertNotIn("Andre", {cast["旁白"].voice, cast["甲"].voice, cast["乙"].voice, cast["机械守卫"].voice})
        self.assertNotEqual(cast["甲"].voice, cast["乙"].voice)
        dialect = {voice.voice_id for voice in QWEN_VOICES if voice.family == "dialect"}
        self.assertIn(cast["机械守卫"].voice, dialect)
        self.assertIn("乙", adjacency_graph(chapters)["甲"])

    def test_same_role_is_assigned_once_across_chapters(self):
        role = ScriptCharacter("旅人", gender="女", age_group="青年")
        chapters = [
            ScriptChapter(1, "一", [ScriptSegment("旅人", "你好")]),
            ScriptChapter(2, "二", [ScriptSegment("旅人", "再见")]),
        ]
        first = assign_cast([role], chapters, "qwen3tts", {})["旅人"].voice
        second = assign_cast([role], chapters, "qwen3tts", {})["旅人"].voice
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
