"""Offline review probes for Voicebook PR #5, commit f234080.

Run from the Voicebook checkout:
    uv run --locked --offline python ../qa-review/reproduce.py
No provider calls; production source is not modified.
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
from book2audio.machine import GenerationCancelled, ProgressEmitter
from book2audio.script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    write_voicebook_script,
)
from book2audio.tool_pipeline import _run_media, generate_audio
from book2audio.work import WorkProgress, render_bounded


def normalization_cancel_gap(root):
    script = root / "book.script"
    write_voicebook_script(
        VoicebookScript(
            title="离线评审",
            characters=[ScriptCharacter("旁白", "旁白", gender="男")],
            chapters=[ScriptChapter(1, "标题", [ScriptSegment("旁白", "正文")])],
        ),
        script,
    )
    cancel = root / "cancel"
    rows = []
    entered = threading.Event()
    times = {}

    class Stream(io.StringIO):
        def write(self, value):
            rows.append((time.monotonic(), json.loads(value)))
            return super().write(value)

    class Synth:
        def synthesize(self, text, voice, engine, output):
            with wave.open(str(output), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(b"\x10\x00" * 1200)

    original_run = subprocess.run

    def delayed_ffmpeg(command, **kwargs):
        if command[0] == "ffmpeg" and ".normalized.wav" in command[-1]:
            times["normalization_start"] = time.monotonic()
            entered.set()
            # A real owned child simulates ffmpeg delayed by CPU/IO load.
            original_run([sys.executable, "-c", "import time; time.sleep(2.2)"], check=True)
            times["normalization_end"] = time.monotonic()
        return original_run(command, **kwargs)

    def cancel_while_processing():
        if not entered.wait(5):
            raise AssertionError("normalization did not start")
        time.sleep(0.1)
        times["cancel_at"] = time.monotonic()
        cancel.touch()

    observer = threading.Thread(target=cancel_while_processing)
    observer.start()
    try:
        with patch("book2audio.tool_pipeline.subprocess.run", delayed_ffmpeg):
            try:
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=Synth(),
                    edge_budget=EdgeBudget(root / "edge.sqlite", interval=0),
                    progress=ProgressEmitter(Stream(), version=2),
                    cancel_file=cancel,
                )
            except GenerationCancelled:
                times["cancelled_at"] = time.monotonic()
            else:
                raise AssertionError("expected cancellation")
    finally:
        observer.join(5)
    events_during_normalization = [
        row["event"]
        for at, row in rows
        if times["normalization_start"] < at < times["normalization_end"]
    ]
    assert not events_during_normalization
    assert times["cancelled_at"] - times["cancel_at"] > 2
    return {
        "case": "normalization_cancel_gap",
        "events_during_2_2s_normalization": events_during_normalization,
        "cancel_latency_seconds": round(times["cancelled_at"] - times["cancel_at"], 3),
        "terminal_event": rows[-1][1]["event"],
    }


def lease_during_local_media(root):
    # Scale the production 120-second lease to 150 ms. All scheduler paths,
    # SQLite transactions, heartbeats and local-media handling are unchanged.
    with (
        patch("book2audio.edge_budget.LEASE_SECONDS", 0.15),
        patch("book2audio.work.HEARTBEAT_SECONDS", 0.01),
        patch("book2audio.tool_pipeline.MEDIA_HEARTBEAT_SECONDS", 0.02),
    ):
        budget = EdgeBudget(root / "lease.sqlite", interval=0, concurrency=2)
        other = EdgeBudget(budget.path, interval=0, concurrency=2)
        long_request_started = threading.Event()
        media_started = threading.Event()
        long_request_active = threading.Event()
        observations = {}
        connection_lock = threading.Lock()
        connections = {"active": 0, "maximum": 0}

        def open_mock_connection():
            with connection_lock:
                connections["active"] += 1
                connections["maximum"] = max(connections["maximum"], connections["active"])

        def close_mock_connection():
            with connection_lock:
                connections["active"] -= 1

        stream = io.StringIO()
        progress = WorkProgress(ProgressEmitter(stream, version=2), ["0", "1", "2"], 1, 2)

        def steps(index, stop):
            def request():
                open_mock_connection()
                try:
                    if index == 1:
                        assert long_request_started.wait(5)
                    elif index == 2:
                        long_request_active.set()
                        long_request_started.set()
                        time.sleep(1)
                        long_request_active.clear()
                finally:
                    close_mock_connection()

            yield request
            if index == 1:
                media_started.set()
                _run_media(
                    [sys.executable, "-c", "import time; time.sleep(0.6)"],
                    work=progress,
                )
            return Path(str(index)), str(index), False

        def complete(index, result):
            progress.complete(str(index), chapter_number=1, segment_index=index - 1, result=result)

        def competing_book():
            if not media_started.wait(5):
                observations["error"] = "media did not start"
                return
            time.sleep(0.25)
            admissions = []
            held = []
            for token in ("other-book-1", "other-book-2"):
                admitted = other.poll(token).admitted
                admissions.append(admitted)
                if admitted:
                    other.start(token)
                    open_mock_connection()
                    held.append(token)
            observations["original_network_request_still_active"] = long_request_active.is_set()
            observations["other_book_admissions"] = admissions
            observations["actual_simulated_connections"] = connections["active"]
            for token, admitted in zip(("other-book-1", "other-book-2"), admissions):
                if admitted:
                    close_mock_connection()
                    other.finish(token)
                else:
                    other.abandon(token)

        competitor = threading.Thread(target=competing_book)
        competitor.start()
        try:
            render_bounded(
                [(str(i), [i]) for i in range(3)],
                None,
                progress,
                list(progress.states),
                complete,
                None,
                0,
                0,
                budget=budget,
                steps=steps,
            )
        finally:
            competitor.join(5)
        observations["heartbeats"] = sum(
            json.loads(line)["event"] == "heartbeat" for line in stream.getvalue().splitlines()
        )
        observations["maximum_simulated_connections"] = connections["maximum"]
        assert observations["actual_simulated_connections"] == 3, observations
        assert connections["active"] == 0
        assert observations["heartbeats"] > 0
        return {"case": "lease_during_local_media", "configured_connection_limit": 2, **observations}


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        results = [normalization_cancel_gap(root), lease_during_local_media(root)]
    target = Path(__file__).with_name("reproduction-results.json")
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.read_text())


if __name__ == "__main__":
    main()
