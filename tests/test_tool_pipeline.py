import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from book2audio.script import (
    ScriptChapter, ScriptCharacter, ScriptSegment, VoicebookScript,
    parse_voicebook_script, write_voicebook_script,
)
from book2audio.tool_pipeline import generate_audio


class FakeSynthesizer:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, engine, output):
        self.calls.append((text, voice, engine))
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24_000)
            wav.writeframes((b"\x10\x00" * 2_400))


class FailingSynthesizer:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text, voice, engine, output):
        self.calls += 1
        raise RuntimeError("Arrearage")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
class ToolPipelineTests(unittest.TestCase):
    def _script(self, path: Path, text="你好。"):
        script = VoicebookScript(
            title="测试书",
            author="作者",
            protagonist_voices={"qwen3tts": {"男": "Andre", "女": "Serena"}},
            characters=[
                ScriptCharacter("旁白", "旁白", gender="男", age_group="中年"),
                ScriptCharacter("甲", gender="男", age_group="青年"),
            ],
            chapters=[ScriptChapter(1, "第一章", [ScriptSegment("旁白", "天亮了。"), ScriptSegment("甲", text)])],
        )
        write_voicebook_script(script, path)

    def test_generates_chapter_mp3_manifest_and_reuses_segment_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "book.script"
            output = root / "out"
            self._script(script)
            fake = FakeSynthesizer()
            files = generate_audio(script, output, engine="qwen3tts", synthesizer=fake)
            first_call_count = len(fake.calls)
            generate_audio(script, output, engine="qwen3tts", synthesizer=fake)
            manifest = json.loads((output / ".voicebook/manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(1, len(files))
            self.assertTrue(files[0].is_file())
            self.assertGreater(files[0].stat().st_size, 100)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format_tags=title,album,artist", "-of", "json", str(files[0])],
                check=True, capture_output=True, text=True,
            )
            tags = json.loads(probe.stdout)["format"]["tags"]
            self.assertEqual(("第一章", "测试书", "作者"), (tags["title"], tags["album"], tags["artist"]))
            self.assertEqual(3, first_call_count)  # 标题 + 旁白 + 对白
            self.assertEqual(first_call_count, len(fake.calls))
            self.assertTrue(all(segment["缓存命中"] for segment in manifest["片段"]))

    def test_editing_one_segment_invalidates_only_that_segment_and_force_invalidates_all(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "book.script"
            output = root / "out"
            fake = FakeSynthesizer()
            self._script(script, "旧对白。")
            generate_audio(script, output, synthesizer=fake)
            initial = len(fake.calls)
            self._script(script, "新对白。")
            generate_audio(script, output, synthesizer=fake)
            after_edit = len(fake.calls)
            generate_audio(script, output, synthesizer=fake, force=True)

            self.assertEqual(initial + 1, after_edit)
            self.assertEqual(after_edit + 3, len(fake.calls))

    def test_first_missing_segment_probes_service_before_starting_parallel_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "book.script"
            self._script(script)
            fake = FailingSynthesizer()
            with self.assertRaisesRegex(RuntimeError, "Arrearage"):
                generate_audio(script, root / "out", synthesizer=fake)
            self.assertEqual(1, fake.calls)

    def test_punctuation_only_segment_is_not_sent_to_tts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script_path = root / "book.script"
            self._script(script_path)
            script = parse_voicebook_script(script_path)
            script.chapters[0].segments.insert(0, ScriptSegment("旁白", "。……"))
            write_voicebook_script(script, script_path)
            fake = FakeSynthesizer()
            generate_audio(script_path, root / "out", synthesizer=fake)
            self.assertNotIn("。……", [call[0] for call in fake.calls])


if __name__ == "__main__":
    unittest.main()
