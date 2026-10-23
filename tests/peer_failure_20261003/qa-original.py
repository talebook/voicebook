"""Extend the PR's peer-failure fixture to Edge concurrency 2, offline.

Run from the verified f3109d0 source:
    uv run --locked --offline python ../qa-rereview/edge_peer_failure.py
The slow media child produces valid output after 2 seconds, then exits normally.
"""

import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from unittest.mock import patch

from book2audio.edge_budget import EdgeBudget
from book2audio.machine import ProgressEmitter
from book2audio.script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    write_voicebook_script,
)
from book2audio.tool_pipeline import generate_audio


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = root / "book.script"
        write_voicebook_script(
            VoicebookScript(
                title="Edge 同伴失败复核",
                characters=[ScriptCharacter("旁白", "旁白", gender="男")],
                chapters=[
                    ScriptChapter(
                        1,
                        "标题",
                        [ScriptSegment("旁白", text) for text in ("失败", "慢媒体", "未提交")],
                    )
                ],
            ),
            script,
        )
        media_entered = threading.Event()
        slow_source = None
        calls = []
        children = []
        times = {}
        original_popen = subprocess.Popen

        class Synth:
            def synthesize(self, text, voice, engine, output):
                nonlocal slow_source
                calls.append({"text": text, "at": time.monotonic()})
                if text == "失败":
                    assert media_entered.wait(5)
                    times["peer_failed_at"] = time.monotonic()
                    raise ValueError("permanent peer failure")
                if text == "慢媒体":
                    slow_source = str(output)
                with wave.open(str(output), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\x10\x00" * 1200)

        def slow_media(command, **kwargs):
            if command[0] == "ffmpeg" and slow_source in command:
                code = (
                    "import time,subprocess; time.sleep(2); "
                    f"subprocess.run({command!r}, check=True)"
                )
                child = original_popen([sys.executable, "-c", code], **kwargs)
                children.append(child)
                media_entered.set()
                return child
            return original_popen(command, **kwargs)

        stream = io.StringIO()
        with (
            patch("book2audio.tool_pipeline.subprocess.Popen", slow_media),
            patch("book2audio.tool_pipeline.MEDIA_HEARTBEAT_SECONDS", 0.025),
            patch("book2audio.work.HEARTBEAT_SECONDS", 0.025),
        ):
            try:
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=Synth(),
                    engine="edgetts",
                    edge_budget=EdgeBudget(root / "edge.sqlite", interval=0, concurrency=2),
                    concurrency=2,
                    max_retries=0,
                    progress=ProgressEmitter(stream, version=2),
                )
            except ValueError as error:
                assert str(error) == "permanent peer failure", str(error)
                times["returned_at"] = time.monotonic()
            else:
                raise AssertionError("expected peer failure")
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        record = {
            "revision": "f3109d00d191066d887b3a76c19d60460bc5b253",
            "case": "edge_peer_failure_while_coordinator_is_in_media",
            "edge_concurrency": 2,
            "cancel_file": False,
            "simulated_media_seconds": 2,
            "failure_reporting_delay_seconds": round(times["returned_at"] - times["peer_failed_at"], 3),
            "child_exit_codes": [child.poll() for child in children],
            "all_children_reaped": all(child.poll() is not None for child in children),
            "subsequent_requests_after_peer_failure": [
                call["text"]
                for call in calls
                if call["at"] > times["peer_failed_at"] and call["text"] == "未提交"
            ],
            "calls": [call["text"] for call in calls],
            "terminal_event": rows[-1]["event"],
            "completed_units": rows[-1]["snapshot"]["completed"],
            "peer_media_was_terminated": children[0].returncode != 0,
        }
        assert record["all_children_reaped"]
        assert record["failure_reporting_delay_seconds"] >= 2
        assert not record["peer_media_was_terminated"]
    target = Path(__file__).with_name("edge-peer-failure-results.json")
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.read_text())


if __name__ == "__main__":
    main()
