"""Regression probes from the independent TB-234 review attachment."""

import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from review_20261003.reproduce import lease_during_local_media, media_cancel

from book2audio.machine import ProgressEmitter
from book2audio.script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    write_voicebook_script,
)
from book2audio.tool_pipeline import generate_audio


class MediaLeaseTests(unittest.TestCase):
    def test_live_request_lease_survives_long_coordinator_media_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            lease_during_local_media(Path(directory))


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe"
)
class MediaCancellationTests(unittest.TestCase):
    def check_media(self, engine, stage):
        with tempfile.TemporaryDirectory() as directory:
            media_cancel(Path(directory), engine=engine, stage=stage)

    def test_edge_normalization_is_observable_and_cancelled(self):
        self.check_media("edgetts", "normalize")

    def test_edge_tempo_is_observable_and_cancelled(self):
        self.check_media("edgetts", "tempo")

    def test_qwen_normalization_is_observable_and_cancelled(self):
        self.check_media("qwen3tts", "normalize")

    def test_qwen_tempo_is_observable_and_cancelled(self):
        self.check_media("qwen3tts", "tempo")

    def test_peer_failure_stops_and_reaps_media_without_cancel_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "book.script"
            write_voicebook_script(
                VoicebookScript(
                    title="模拟书",
                    characters=[ScriptCharacter("旁白", "旁白", gender="男")],
                    chapters=[
                        ScriptChapter(
                            1,
                            "标题",
                            [
                                ScriptSegment("旁白", text)
                                for text in ("失败", "慢媒体", "未提交")
                            ],
                        )
                    ],
                ),
                script,
            )
            media_entered = threading.Event()
            slow_source = None
            calls = []
            children = []
            original_popen = subprocess.Popen

            class Synth:
                def synthesize(self, text, voice, engine, output):
                    nonlocal slow_source
                    calls.append(text)
                    if text == "失败":
                        assert media_entered.wait(5)
                        raise ValueError("permanent peer failure")
                    if text == "慢媒体":
                        slow_source = str(output)
                    with wave.open(str(output), "wb") as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(24_000)
                        wav.writeframes(b"\x10\x00" * 1200)

            def slow_media(command, **kwargs):
                if command[0] == "ffmpeg" and slow_source in command:
                    child = original_popen(
                        [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
                    )
                    children.append(child)
                    media_entered.set()
                    return child
                return original_popen(command, **kwargs)

            stream = io.StringIO()
            started = time.monotonic()
            with (
                patch("book2audio.tool_pipeline.subprocess.Popen", slow_media),
                patch("book2audio.work.HEARTBEAT_SECONDS", 0.025),
                self.assertRaisesRegex(ValueError, "permanent peer failure"),
            ):
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=Synth(),
                    engine="qwen3tts",
                    concurrency=2,
                    max_retries=0,
                    progress=ProgressEmitter(stream, version=2),
                )
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertNotIn("未提交", calls)
            self.assertTrue(
                children and all(child.poll() is not None for child in children)
            )
            latest = json.loads((root / "out/.voicebook/progress.v2.json").read_text())
            self.assertEqual("failed", latest["event"])
            self.assertEqual(0, latest["snapshot"]["active_requests"])
            self.assertEqual(1, latest["snapshot"]["completed"])


if __name__ == "__main__":
    unittest.main()
