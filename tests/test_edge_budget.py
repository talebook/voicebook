import asyncio
import io
import json
import multiprocessing
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import edge_tts

from book2audio.edge_budget import EdgeBudget
from book2audio.machine import GenerationCancelled, ProgressEmitter
from book2audio.provider_errors import (
    ErrorInfo,
    error_info,
    parse_retry_after,
    safe_error,
)
from book2audio.tts import EdgeEngine, VoiceSpec
from book2audio.work import WaitBudgetExceeded, WorkProgress, render_bounded


def response_error(status, headers=None):
    return aiohttp.ClientResponseError(
        SimpleNamespace(real_url="https://secret.invalid/?token=PRIVATE"),
        (),
        status=status,
        message="SECRET_TEXT",
        headers=headers or {},
    )


def process_book(path, name, log, active, maximum, barrier):
    # All work is a local mock; two independent Python processes share SQLite.
    import book2audio.work as work_module

    work_module.HEARTBEAT_SECONDS = 0.005
    budget = EdgeBudget(Path(path), interval=0.03, concurrency=1)
    barrier.wait(timeout=5)
    progress = WorkProgress(ProgressEmitter(stream=None), ["0", "1", "2"], 1, 3)
    attempts = {}

    def steps(index, stop):
        def request():
            with active.get_lock():
                active.value += 1
                maximum.value = max(maximum.value, active.value)
            attempts[index] = attempts.get(index, 0) + 1
            log.put((name, index, attempts[index], time.time()))
            try:
                time.sleep(0.015)
                if name == "A" and index == 1 and attempts[index] == 1:
                    raise response_error(429, {"Retry-After": "0.04"})
            finally:
                with active.get_lock():
                    active.value -= 1

        yield request
        return Path(str(index)), str(index), False

    def complete(index, result):
        progress.complete(str(index), chapter_number=1, segment_index=index - 1, result=result)

    render_bounded(
        [(str(i), [i]) for i in range(3)],
        None,
        progress,
        ["0", "1", "2"],
        complete,
        None,
        2,
        0.01,
        budget=budget,
        steps=steps,
    )
    log.put((name, "done", progress.emitter.snapshot))


class EdgeBudgetTests(unittest.TestCase):
    def test_fifo_connections_interval_and_abandoned_waiter(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("book2audio.edge_budget.time.time", return_value=1000000) as clock,
        ):
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=5, concurrency=1)
            other = EdgeBudget(budget.path, interval=5, concurrency=1)
            self.assertTrue(budget.poll("first").admitted)
            budget.start("first")
            self.assertEqual("global_concurrency", other.poll("second").reason)
            budget.finish("first")
            self.assertEqual("request_interval", other.poll("second").reason)
            clock.return_value += 5
            self.assertEqual("fair_queue", budget.poll("third").reason)
            self.assertTrue(other.poll("second").admitted)
            other.start("second")
            other.finish("second")
            budget.abandon("third")
            clock.return_value += 5
            self.assertTrue(budget.poll("fourth").admitted)
            budget.start("fourth")
            budget.finish("fourth")
            self.assertEqual(3, budget.stats()["requests"])

    def test_retry_after_and_consecutive_failures_open_shared_cooldown(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("book2audio.edge_budget.time.time", return_value=1000000) as clock,
        ):
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=0, cooldown_seconds=30)
            self.assertTrue(budget.poll("one").admitted)
            budget.start("one")
            budget.finish("one", ErrorInfo(True, 75, 429, "rate_limited"))
            self.assertEqual(1000075, budget.poll("two").next_at)
            self.assertEqual("shared_cooldown", budget.poll("two").reason)
            clock.return_value += 75
            for token in ("two", "three"):
                self.assertTrue(budget.poll(token, retry=True).admitted)
                budget.start(token)
                budget.finish(token, ErrorInfo(True, None, 429, "rate_limited"))
            self.assertEqual("shared_cooldown", budget.poll("four").reason)
            self.assertEqual(1000105, budget.poll("four").next_at)
            self.assertEqual(
                (3, 3, 2, 1), tuple(budget.stats()[key] for key in ("requests", "rate_limits", "retries", "cooldowns"))
            )

    def test_configured_window_budget_and_expired_owner_lease(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("book2audio.edge_budget.time.time", return_value=1000000) as clock,
        ):
            budget = EdgeBudget(Path(directory) / "quota.sqlite", interval=0, request_limit=1, window_seconds=10)
            self.assertTrue(budget.poll("a").admitted)
            budget.start("a")
            budget.finish("a")
            self.assertEqual("request_budget", budget.poll("b").reason)
            clock.return_value += 10
            self.assertTrue(budget.poll("b", retry=True).admitted)
            budget.start("b")
            clock.return_value += 121  # Simulate a crashed owner with no renewals.
            self.assertTrue(budget.poll("c").admitted)
            budget.start("c")
            budget.finish("c")

    def test_conflicting_worker_configuration_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.sqlite"
            EdgeBudget(path)
            with self.assertRaisesRegex(ValueError, "配置不一致"):
                EdgeBudget(path, interval=0)

    def test_multiple_process_books_and_retry_share_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("spawn")
            log = context.Queue()
            active, maximum = context.Value("i", 0), context.Value("i", 0)
            path = str(Path(directory) / "shared.sqlite")
            EdgeBudget(Path(path), interval=0.03, concurrency=1)
            barrier = context.Barrier(2)
            processes = [
                context.Process(target=process_book, args=(path, name, log, active, maximum, barrier))
                for name in ("A", "B")
            ]
            try:
                for process in processes:
                    process.start()
                events = [log.get(timeout=10) for _ in range(9)]  # Consume IPC output before joining its producers.
                for process in processes:
                    process.join(5)
                    self.assertEqual(0, process.exitcode)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join()
                log.close()
            calls = sorted([event for event in events if event[1] != "done"], key=lambda event: event[3])
            self.assertEqual(7, len(calls))
            self.assertEqual(1, maximum.value)
            self.assertTrue(all(second[3] - first[3] >= 0.025 for first, second in zip(calls, calls[1:])))
            self.assertEqual({"A", "B"}, {event[0] for event in calls})
            snapshots = [event[2] for event in events if event[1] == "done"]
            self.assertTrue(all(snapshot["completed"] == 3 for snapshot in snapshots))
            self.assertEqual(
                (7, 1, 1),
                tuple(
                    EdgeBudget(Path(path), interval=0.03).stats()[key] for key in ("requests", "rate_limits", "retries")
                ),
            )


class ProviderMetadataTests(unittest.TestCase):
    def test_retry_after_seconds_dates_missing_invalid_and_past(self):
        now = 1000000.0
        future = format_datetime(datetime.fromtimestamp(now + 120, timezone.utc), usegmt=True)
        past = format_datetime(datetime.fromtimestamp(now - 1, timezone.utc), usegmt=True)
        self.assertEqual(120, parse_retry_after(future, now))
        self.assertEqual(0, parse_retry_after(past, now))
        self.assertEqual(7.5, parse_retry_after("7.5", now))
        for value in (None, "", "bad", "nan", "inf", "-1"):
            self.assertIsNone(parse_retry_after(value, now))

    def test_aiohttp_status_headers_are_preserved_and_network_is_distinct(self):
        info = error_info(response_error(429, {"Retry-After": "61"}))
        self.assertEqual(
            (True, 61, 429, "rate_limited"), (info.retryable, info.retry_after, info.http_status, info.reason)
        )
        self.assertEqual("network_error", error_info(aiohttp.ServerDisconnectedError()).reason)
        self.assertFalse(error_info(response_error(403)).retryable)
        message = safe_error(response_error(429))
        self.assertNotIn("PRIVATE", message)
        self.assertNotIn("SECRET_TEXT", message)
        self.assertIn("429", message)

    def test_pinned_sdk_adapter_prevents_hidden_403_retry(self):
        calls = []

        async def fail(self):
            calls.append(1)
            if False:
                yield {}
            raise response_error(403)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(edge_tts.Communicate, "_Communicate__stream", fail),
        ):
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(
                    EdgeEngine(max_attempts=1, single_request=True).synth(
                        "PRIVATE_TEXT", VoiceSpec("zh-CN-YunxiNeural"), Path(directory) / "audio.mp3"
                    )
                )
        self.assertEqual(1, len(calls))
        self.assertEqual(403, error_info(raised.exception).http_status)
        self.assertNotIn("PRIVATE_TEXT", str(raised.exception))

    def test_sdk_clock_adjustment_returns_to_coordinator_before_retry(self):
        calls = []

        async def fail(self):
            calls.append(1)
            if False:
                yield {}
            raise response_error(403, {"Date": format_datetime(datetime.now(timezone.utc), usegmt=True)})

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(edge_tts.Communicate, "_Communicate__stream", fail),
            patch("edge_tts.drm.DRM.handle_client_response_error"),
        ):
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(
                    EdgeEngine(max_attempts=1, single_request=True).synth(
                        "模拟", VoiceSpec("zh-CN-YunxiNeural"), Path(directory) / "audio.mp3"
                    )
                )
        self.assertEqual(1, len(calls))
        info = error_info(raised.exception)
        self.assertTrue(info.retryable)
        self.assertEqual("clock_skew_adjustment", info.reason)


class WaitingProgressTests(unittest.TestCase):
    def run_steps(self, budget, steps, *, cancel=None, max_wait=300, stream=None, count=2):
        stream = stream if stream is not None else io.StringIO()
        progress = WorkProgress(ProgressEmitter(stream, version=2), [str(i) for i in range(count)], 1, 2)
        progress.stage = "synthesizing"

        def completed(index, result):
            progress.complete(str(index), chapter_number=1, segment_index=index - 1, result=result)

        with patch("book2audio.work.HEARTBEAT_SECONDS", 0.005):
            result = render_bounded(
                [(str(i), [i]) for i in range(count)],
                None,
                progress,
                list(progress.states),
                completed,
                cancel,
                2,
                0.02,
                budget=budget,
                steps=steps,
                max_wait_seconds=max_wait,
            )
        return result, [json.loads(line) for line in stream.getvalue().splitlines()]

    def test_long_logical_unit_every_chunk_uses_shared_start_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=0.025)
            calls = []

            def steps(index, stop):
                for chunk in range(3):

                    def request(index=index, chunk=chunk):
                        calls.append((index, chunk, time.time()))

                    yield request
                return Path(str(index)), str(index), False

            result, rows = self.run_steps(budget, steps)
            self.assertEqual(2, len(result))
            self.assertEqual(6, len(calls))
            self.assertTrue(all(b[2] - a[2] >= 0.024 for a, b in zip(calls, calls[1:])))
            self.assertTrue(any(row["snapshot"]["status"] == "rate_queued" for row in rows))
            for row in rows:
                value = row["snapshot"]
                self.assertEqual(
                    2,
                    sum(
                        value[key]
                        for key in ("completed", "active", "retrying", "failed", "cancelled", "pending", "queued")
                    ),
                )
                if value["status"] == "rate_queued":
                    self.assertEqual(0, value["active_requests"])

    def test_peer_failure_while_preparing_next_generator_keeps_failure_identity(self):
        started = threading.Event()
        release = threading.Event()
        calls = []
        stream = io.StringIO()

        def steps(index, stop):
            if index == 3:
                release.set()
                self.assertTrue(stop.wait(3))
                raise GenerationCancelled("peer stopped preparation")

            def request():
                calls.append(index)
                if index == 1:
                    self.assertTrue(started.wait(3))
                elif index == 2:
                    started.set()
                    self.assertTrue(release.wait(3))
                    raise ValueError("original provider failure")

            yield request
            return Path(str(index)), str(index), False

        with tempfile.TemporaryDirectory() as directory:
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=0, concurrency=2)
            with self.assertRaisesRegex(ValueError, "original provider failure"):
                self.run_steps(budget, steps, count=4, stream=stream)
        self.assertEqual({0, 1, 2}, set(calls))
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(1, sum(row["event"] == "unit_failed" for row in rows))
        self.assertFalse(any(row["event"] == "cancel_requested" for row in rows))
        self.assertEqual(1, rows[-1]["snapshot"]["failed"])

    def test_shared_cooldown_is_visible_persisted_and_cancelled_without_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = EdgeBudget(root / "budget.sqlite", interval=0)
            self.assertTrue(budget.poll("provider").admitted)
            budget.start("provider")
            budget.finish("provider", ErrorInfo(True, 60, 429, "rate_limited"))
            cancel = root / "cancel"
            calls = []

            def steps(index, stop):
                yield lambda: calls.append(index)
                return Path(str(index)), str(index), False

            class Stream(io.StringIO):
                def write(self, value):
                    row = json.loads(value)
                    if row["snapshot"]["status"] == "cooling_down":
                        cancel.touch()
                    return super().write(value)

            stream = Stream()
            with self.assertRaises(GenerationCancelled):
                self.run_steps(budget, steps, cancel=cancel, stream=stream)
            self.assertEqual([], calls)
            row = json.loads(stream.getvalue().splitlines()[0])
            self.assertEqual("shared_cooldown", row["snapshot"]["waiting"]["reason"])
            self.assertIsNotNone(row["snapshot"]["waiting"]["next_request_at"])
            self.assertEqual(0, row["snapshot"]["completed"])

    def test_retry_budget_exhaustion_never_retries_before_retry_after(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=0)
            calls = []
            stream = io.StringIO()

            def steps(index, stop):
                def request():
                    calls.append(time.time())
                    raise response_error(429, {"Retry-After": "90"})

                yield request
                return Path(str(index)), str(index), False

            with self.assertRaises(WaitBudgetExceeded):
                self.run_steps(budget, steps, max_wait=0.02, stream=stream, count=1)
            self.assertEqual(1, len(calls))
            retry = next(
                json.loads(line)
                for line in stream.getvalue().splitlines()
                if json.loads(line)["event"] == "unit_retrying"
            )
            self.assertEqual(90, retry["retry_in_seconds"])
            self.assertEqual("rate_limit_retry", retry["snapshot"]["status"])
            self.assertEqual(0, retry["snapshot"]["completed"])

    def test_missing_retry_after_uses_jittered_exponential_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = EdgeBudget(Path(directory) / "budget.sqlite", interval=0)
            attempts = []

            def steps(index, stop):
                def request():
                    attempts.append(time.time())
                    if len(attempts) < 3:
                        raise response_error(429)

                yield request
                return Path(str(index)), str(index), False

            with patch("book2audio.work.random.uniform", side_effect=lambda low, high: high) as jitter:
                _, rows = self.run_steps(budget, steps, count=1)
            self.assertEqual([(0.02, 0.03), (0.04, 0.06)], [call.args for call in jitter.call_args_list])
            self.assertGreaterEqual(attempts[1] - attempts[0], 0.03)
            self.assertGreaterEqual(attempts[2] - attempts[1], 0.06)
            self.assertEqual(1, rows[-1]["snapshot"]["completed"])


if __name__ == "__main__":
    unittest.main()
