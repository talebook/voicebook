"""QA attachment probes adapted to assert the corrected production behavior.

Run from the Voicebook checkout:
    uv run --locked --offline python tests/review_20261003/reproduce.py
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


def media_cancel(root, *, stage="normalize", engine="edgetts"):
    root.mkdir(parents=True, exist_ok=True)
    script = root / "book.script"
    write_voicebook_script(
        VoicebookScript(
            title="离线评审",
            characters=[ScriptCharacter("旁白", "旁白", gender="男", speed="x1.2")],
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

    original_popen = subprocess.Popen
    children = []

    def delayed_ffmpeg(command, **kwargs):
        target = ".normalized.wav" in command[-1] if stage == "normalize" else "-filter:a" in command
        if command[0] == "ffmpeg" and target:
            times["media_start"] = time.monotonic()
            child = original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(child)
            entered.set()
            return child
        return original_popen(command, **kwargs)

    def cancel_while_processing():
        if not entered.wait(5):
            times["observer_error"] = "media did not start"
            return
        time.sleep(0.15)
        times["cancel_at"] = time.monotonic()
        cancel.touch()

    observer = threading.Thread(target=cancel_while_processing)
    observer.start()
    try:
        with (
            patch("book2audio.tool_pipeline.subprocess.Popen", delayed_ffmpeg),
            patch("book2audio.tool_pipeline.MEDIA_HEARTBEAT_SECONDS", 0.025),
            patch("book2audio.work.HEARTBEAT_SECONDS", 0.025),
        ):
            try:
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=Synth(),
                    engine=engine,
                    edge_budget=EdgeBudget(root / "edge.sqlite", interval=0) if engine == "edgetts" else None,
                    progress=ProgressEmitter(Stream(), version=2),
                    cancel_file=cancel,
                )
            except GenerationCancelled:
                times["cancelled_at"] = time.monotonic()
            else:
                raise AssertionError("expected cancellation")
    finally:
        observer.join(5)
    assert not observer.is_alive() and "observer_error" not in times, times
    events_during_media = [
        row["event"]
        for at, row in rows
        if times["media_start"] < at < times["cancel_at"]
    ]
    latency = times["cancelled_at"] - times["cancel_at"]
    assert "heartbeat" in events_during_media, events_during_media
    assert latency < 0.75, latency
    assert children and all(child.poll() is not None for child in children)
    assert rows[-1][1]["event"] == "cancelled"
    assert not any(row["event"] == "completed" for _, row in rows)
    assert not list((root / "out/.voicebook/cache").glob("render_*"))
    assert not list((root / "out/.voicebook/cache").glob("*.wav"))
    latest = json.loads((root / "out/.voicebook/progress.v2.json").read_text())
    assert latest == rows[-1][1] and latest["snapshot"]["active_requests"] == 0
    return {
        "case": f"{engine}_{stage}_cancel",
        "simulated_child_seconds": 30,
        "events_before_cancel_during_media": events_during_media,
        "cancel_latency_seconds": round(latency, 3),
        "all_children_reaped": True,
        "terminal_event": rows[-1][1]["event"],
    }


def lease_during_local_media(root):
    root.mkdir(parents=True, exist_ok=True)
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
        assert observations["original_network_request_still_active"], observations
        assert observations["other_book_admissions"] == [True, False], observations
        assert observations["actual_simulated_connections"] == 2, observations
        assert observations["maximum_simulated_connections"] == 2, observations
        assert connections["active"] == 0
        assert observations["heartbeats"] > 0
        assert not progress.request_tokens
        return {"case": "lease_during_local_media", "configured_connection_limit": 2, **observations}


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        results = [lease_during_local_media(root / "lease")]
        results.extend(
            media_cancel(root / f"{engine}-{stage}", stage=stage, engine=engine)
            for engine in ("edgetts", "qwen3tts") for stage in ("normalize", "tempo")
        )
    target = Path(__file__).with_name("after.json")
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.read_text())


if __name__ == "__main__":
    main()
