import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
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
from book2audio.tts import QwenTTSAPIError
from book2audio.work import WorkProgress, render_bounded


class ObservedStream(io.StringIO):
    def __init__(self, observe=lambda _row: None):
        super().__init__()
        self.rows = []
        self.observe = observe

    def write(self, value):
        row = json.loads(value)
        self.rows.append(row)
        self.observe(row)
        return super().write(value)


class BoundedRenderingTests(unittest.TestCase):
    def run_jobs(
        self,
        render,
        *,
        count=8,
        concurrency=2,
        max_retries=2,
        stream=None,
        cancel_file=None,
        jobs=None,
    ):
        stream = stream if stream is not None else ObservedStream()
        work = WorkProgress(
            ProgressEmitter(stream, version=2),
            [str(i) for i in range(count)],
            1,
            concurrency,
        )
        work.stage = "synthesizing"

        def complete(index, result):
            work.complete(str(index), chapter_number=1, segment_index=index - 1, result=result)

        result = render_bounded(
            jobs if jobs is not None else [(str(i), [i]) for i in range(count)],
            render,
            work,
            [str(i) for i in range(count)],
            complete,
            cancel_file,
            max_retries,
            0.01,
        )
        return result, stream.rows, work

    def assert_counts(self, rows):
        for row in rows:
            snapshot = row["snapshot"]
            self.assertEqual(
                snapshot["total"],
                sum(
                    snapshot[key]
                    for key in (
                        "completed",
                        "active",
                        "retrying",
                        "failed",
                        "cancelled",
                        "pending",
                    )
                ),
            )
            self.assertLessEqual(snapshot["active_requests"], snapshot["concurrency"])
        self.assertEqual(list(range(1, len(rows) + 1)), [row["seq"] for row in rows])
        completed = [row["snapshot"]["completed"] for row in rows]
        self.assertEqual(sorted(completed), completed)

    def test_out_of_order_live_progress_and_duplicate_fingerprints(self):
        release = threading.Event()
        lock = threading.Lock()
        running = 0
        maximum = 0
        calls = []

        def render(index, _stop):
            nonlocal running, maximum
            with lock:
                calls.append(index)
                running += 1
                maximum = max(maximum, running)
            try:
                if index == 1:
                    self.assertTrue(
                        release.wait(3),
                        "slow request must be released by live progress",
                    )
                else:
                    time.sleep(0.02)
                return Path(str(index)), str(index), False
            finally:
                with lock:
                    running -= 1

        def observe(row):
            if row.get("unit_id") == "2" and row["event"] == "segment_completed":
                self.assertEqual(1, row["snapshot"]["active_requests"])
                self.assertEqual(2, row["snapshot"]["completed"])
                release.set()

        result, rows, _ = self.run_jobs(
            render,
            stream=ObservedStream(observe),
            jobs=[("0", [0]), ("1", [1]), ("2", [2, 3])] + [(str(i), [i]) for i in range(4, 8)],
        )
        self.assertEqual(set(range(8)), set(result))
        self.assertEqual(result[2], result[3])
        self.assertEqual(7, len(calls))
        self.assertEqual(2, maximum)
        self.assertEqual(0, running)
        self.assert_counts(rows)

    def test_rate_limit_retry_is_bounded_and_completed_once(self):
        calls = []

        def render(index, _stop):
            calls.append(index)
            if calls.count(index) == 1 and index == 1:
                raise QwenTTSAPIError("429", retryable=True, retry_after=0.01)
            return Path(str(index)), str(index), False

        _, rows, work = self.run_jobs(render, count=3)
        self.assertEqual(2, calls.count(1))
        self.assertEqual(1, work.retries)
        self.assertEqual(3, rows[-1]["snapshot"]["completed"])
        self.assertEqual(
            1,
            len([row for row in rows if row["event"] == "segment_completed" and row["unit_id"] == "1"]),
        )
        self.assertTrue(any(row["snapshot"]["status"] == "retrying" for row in rows))
        self.assertEqual("running", rows[-1]["snapshot"]["status"])
        self.assert_counts(rows)

    def test_probe_does_not_fan_out_permanent_failure(self):
        calls = []

        def render(index, _stop):
            calls.append(index)
            raise QwenTTSAPIError("403 Arrearage", retryable=False)

        with self.assertRaisesRegex(QwenTTSAPIError, "Arrearage"):
            self.run_jobs(render)
        self.assertEqual([0], calls)

    def test_failure_completed_between_results_is_drained_before_next_submission(self):
        for failure in (ValueError("peer failed"), QwenTTSAPIError("budget exhausted", retryable=True)):
            with self.subTest(failure=type(failure).__name__):
                started = threading.Event()
                release = threading.Event()
                calls = []
                control = None

                def render(index, stop):
                    nonlocal control
                    control = stop
                    calls.append(index)
                    if index == 1:
                        self.assertTrue(started.wait(3))
                    elif index == 2:
                        started.set()
                        self.assertTrue(release.wait(3))
                        raise failure
                    return Path(str(index)), str(index), False

                def observe(row):
                    if row["event"] == "segment_completed" and row["unit_id"] == "1":
                        release.set()
                        # The failure becomes observable after one result was handled,
                        # while the coordinator is still inside its completion callback.
                        self.assertTrue(control.wait(3))

                stream = ObservedStream(observe)
                with self.assertRaises(type(failure)):
                    self.run_jobs(render, count=4, max_retries=0, stream=stream)
                self.assertEqual({0, 1, 2}, set(calls))
                self.assertEqual(1, stream.rows[-1]["snapshot"]["failed"])
                self.assert_counts(stream.rows)

    def test_retry_budget_exhaustion_has_no_completed_increase(self):
        calls = []
        stream = ObservedStream()

        def render(index, _stop):
            calls.append(index)
            raise QwenTTSAPIError("503", retryable=True, retry_after=0)

        with self.assertRaises(QwenTTSAPIError):
            self.run_jobs(render, max_retries=1, stream=stream)
        self.assertEqual([0, 0], calls)
        self.assertEqual(0, stream.rows[-1]["snapshot"]["completed"])
        self.assertEqual(1, stream.rows[-1]["snapshot"]["failed"])
        self.assert_counts(stream.rows)

    def test_cancel_stops_submissions_and_drains_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = Path(directory) / "cancel"
            calls = []
            running = 0
            lock = threading.Lock()

            def render(index, stop):
                nonlocal running
                with lock:
                    calls.append(index)
                    running += 1
                try:
                    if index:
                        time.sleep(0.05)
                    if stop.is_set() or cancel.exists():
                        raise GenerationCancelled("cancelled")
                    return Path(str(index)), str(index), False
                finally:
                    with lock:
                        running -= 1

            def observe(row):
                if row["event"] == "unit_started" and row["snapshot"]["active_requests"] == 2:
                    cancel.touch()

            stream = ObservedStream(observe)
            with (
                patch("book2audio.work.HEARTBEAT_SECONDS", 0.01),
                self.assertRaises(GenerationCancelled),
            ):
                self.run_jobs(render, stream=stream, cancel_file=cancel)
            self.assertLessEqual(len(calls), 3)
            self.assertEqual(0, running)
            self.assertTrue(any(row["snapshot"]["status"] == "cancelling" for row in stream.rows))
            self.assert_counts(stream.rows)

    def test_cancel_interrupts_long_retry_after(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = Path(directory) / "cancel"
            calls = []

            def render(index, _stop):
                calls.append(index)
                raise QwenTTSAPIError("429", retryable=True, retry_after=999)

            stream = ObservedStream(lambda row: cancel.touch() if row["event"] == "unit_retrying" else None)
            started = time.monotonic()
            with self.assertRaises(GenerationCancelled):
                self.run_jobs(render, stream=stream, cancel_file=cancel)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual([0], calls)
            self.assertEqual(
                999,
                next(row for row in stream.rows if row["event"] == "unit_retrying")["retry_in_seconds"],
            )

    def test_slow_probe_emits_heartbeats_without_fake_completion(self):
        def render(index, _stop):
            time.sleep(0.07)
            return Path(str(index)), str(index), False

        with patch("book2audio.work.HEARTBEAT_SECONDS", 0.01):
            _, rows, _ = self.run_jobs(render, count=1)
        heartbeats = [row for row in rows if row["event"] == "heartbeat"]
        self.assertGreaterEqual(len(heartbeats), 2)
        self.assertTrue(all(row["snapshot"]["completed"] == 0 for row in heartbeats))
        self.assert_counts(rows)

    def test_fatal_failure_drains_active_workers_before_raising(self):
        calls = []
        finished = threading.Event()
        started = threading.Event()

        def render(index, stop):
            calls.append(index)
            if index == 1:
                self.assertTrue(started.wait(3))
                raise ValueError("permanent failure")
            if index == 2:
                started.set()
                self.assertTrue(stop.wait(3))
                finished.set()
                raise GenerationCancelled("stopped after peer failure")
            return Path(str(index)), str(index), False

        stream = ObservedStream()
        with self.assertRaisesRegex(ValueError, "permanent failure"):
            self.run_jobs(render, stream=stream)
        self.assertTrue(finished.is_set())
        self.assertEqual([0, 1, 2], sorted(calls))
        self.assertEqual(1, stream.rows[-1]["snapshot"]["completed"])
        self.assert_counts(stream.rows)

    def test_assembly_heartbeat_and_cancel_reap_the_media_child(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = Path(directory) / "cancel"
            stream = ObservedStream(lambda row: cancel.touch() if row["event"] == "heartbeat" else None)
            work = WorkProgress(ProgressEmitter(stream), ["title"], 1, 1)
            work.stage = "assembling"
            with (
                patch("book2audio.tool_pipeline.MEDIA_HEARTBEAT_SECONDS", 0.02),
                self.assertRaises(GenerationCancelled),
            ):
                _run_media(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    work=work,
                    cancel_file=cancel,
                )
            self.assertTrue(stream.rows)
            self.assertEqual("assembling", stream.rows[0]["snapshot"]["stage"])


class WavSynthesizer:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, voice, engine, output):
        self.calls.append(text)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24_000)
            wav.writeframes(b"\x10\x00" * 1200)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
class GenerationContractTests(unittest.TestCase):
    def script(self, root, chapters=2, text=None):
        script = VoicebookScript(
            title="模拟书",
            characters=[ScriptCharacter("旁白", "旁白", gender="男")],
            chapters=[
                ScriptChapter(
                    number,
                    f"第{number}章",
                    [
                        ScriptSegment("旁白", value)
                        for value in (
                            text
                            or [
                                f"第{number}章首段",
                                f"第{number}章次段",
                                f"第{number}章首段",
                            ]
                        )
                    ],
                )
                for number in range(1, chapters + 1)
            ],
        )
        path = root / "book.script"
        write_voicebook_script(script, path)
        return path

    def test_book_totals_output_order_persistence_and_fresh_resume_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self.script(root)
            output = root / "out"
            stream = ObservedStream()
            fake = WavSynthesizer()
            first = ProgressEmitter(stream, version=2, task_id="job-123")
            files = generate_audio(script, output, synthesizer=fake, progress=first, concurrency=2)
            self.assertEqual(["0001.mp3", "0002.mp3"], [path.name for path in files])
            self.assertEqual(6, len(fake.calls))  # 2 titles + 2 unique body segments per chapter
            self.assertEqual(8, stream.rows[0]["snapshot"]["total"])
            self.assertEqual(0, stream.rows[0]["snapshot"]["completed"])
            for number in (1, 2):
                timeline = json.loads((output / f"timelines/{number:04d}.json").read_text())
                self.assertEqual(
                    [f"第{number}章首段", f"第{number}章次段", f"第{number}章首段"],
                    [segment["text"] for segment in timeline["segments"]],
                )
                self.assertEqual([0, 1, 2], [segment["index"] for segment in timeline["segments"]])
            before_terminal = [
                row for row in stream.rows if row["snapshot"]["completed"] == 8 and row["event"] != "completed"
            ]
            self.assertTrue(before_terminal)
            self.assertTrue(all(row["snapshot"]["status"] != "completed" for row in before_terminal))
            latest = json.loads((output / ".voicebook/progress.v2.json").read_text())
            self.assertEqual(stream.rows[-1], latest)
            self.assertEqual(
                ("completed", 8, 2),
                (
                    latest["snapshot"]["status"],
                    latest["snapshot"]["completed"],
                    latest["snapshot"]["chapters_completed"],
                ),
            )
            second_stream = ObservedStream()
            second = ProgressEmitter(second_stream, version=2, task_id="job-123")
            generate_audio(script, output, synthesizer=fake, progress=second, resume=True)
            self.assertEqual(6, len(fake.calls))
            self.assertNotEqual(first.attempt_id, second.attempt_id)
            self.assertEqual(0, second_stream.rows[0]["snapshot"]["completed"])
            self.assertEqual(8, second_stream.rows[-1]["snapshot"]["cache_hits"])

    def test_force_does_not_skip_resumed_chapters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self.script(root, chapters=1)
            fake = WavSynthesizer()
            generate_audio(script, root / "out", synthesizer=fake)
            generate_audio(script, root / "out", synthesizer=fake, resume=True, force=True)
            self.assertEqual(6, len(fake.calls))

    def test_edge_pipeline_all_text_chunks_enter_shared_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self.script(root, chapters=1, text=["长文。" * 300, "短段"])
            budget = EdgeBudget(root / "budget.sqlite", interval=0.001)
            fake = WavSynthesizer()
            stream = ObservedStream()
            with patch("book2audio.work.HEARTBEAT_SECONDS", 0.01):
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=fake,
                    edge_budget=budget,
                    concurrency=2,
                    progress=ProgressEmitter(stream, version=2),
                )
            self.assertEqual(4, len(fake.calls))
            self.assertEqual(4, budget.stats()["requests"])
            self.assertEqual(
                (3, 4), (stream.rows[-1]["snapshot"]["completed"], stream.rows[-1]["snapshot"]["requests_started"])
            )
            self.assertTrue(any(row["snapshot"]["queued"] for row in stream.rows))

    def test_encoding_failure_never_reports_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self.script(root, chapters=1)
            stream = ObservedStream()
            with (
                patch(
                    "book2audio.tool_pipeline._encode_mp3",
                    side_effect=RuntimeError("encoding failed"),
                ),
                self.assertRaises(RuntimeError),
            ):
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=WavSynthesizer(),
                    progress=ProgressEmitter(stream),
                )
            self.assertEqual("failed", stream.rows[-1]["event"])
            self.assertEqual("failed", stream.rows[-1]["snapshot"]["status"])
            self.assertEqual(4, stream.rows[-1]["snapshot"]["completed"])
            self.assertEqual(0, stream.rows[-1]["snapshot"]["chapters_completed"])
            self.assertFalse(any(row["event"] == "completed" for row in stream.rows))
            self.assertEqual(
                "failed",
                json.loads((root / "out/manifest.v2.json").read_text())["status"],
            )

    def test_cancel_during_long_segment_does_not_call_next_text_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cancel = root / "cancel"
            script = self.script(root, chapters=1, text=["长对白。" * 500])
            fake = WavSynthesizer()
            original = fake.synthesize

            def synthesize(text, voice, engine, output):
                original(text, voice, engine, output)
                if text.startswith("长对白"):
                    cancel.touch()

            fake.synthesize = synthesize
            stream = ObservedStream()
            with self.assertRaises(GenerationCancelled):
                generate_audio(
                    script,
                    root / "out",
                    synthesizer=fake,
                    concurrency=1,
                    cancel_file=cancel,
                    progress=ProgressEmitter(stream),
                )
            self.assertEqual(2, len(fake.calls))  # title + first API chunk
            self.assertEqual("cancelled", stream.rows[-1]["event"])
            self.assertEqual(1, stream.rows[-1]["snapshot"]["completed"])
            self.assertEqual(0, stream.rows[-1]["snapshot"]["active"])


if __name__ == "__main__":
    unittest.main()
