"""Bounded rendering and attempt-local, absolute progress counters.

Workers only render audio. The coordinator owns progress and all event writes.
"""

from __future__ import annotations

import random
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from uuid import uuid4

from .machine import GenerationCancelled, ProgressEmitter
from .provider_errors import error_info

HEARTBEAT_SECONDS = 1.0


def retry_details(error: Exception) -> tuple[bool, float | None]:
    info = error_info(error)
    return info.retryable, info.retry_after


class WaitBudgetExceeded(RuntimeError):
    retryable = True
    reason = "retry_wait_budget"


def _utc(timestamp):
    try:
        return (
            datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
            if timestamp is not None
            else None
        )
    except (ValueError, OverflowError, OSError):
        return None


class WorkProgress:
    def __init__(
        self,
        emitter: ProgressEmitter,
        units: list[str],
        chapters_total: int,
        concurrency: int,
    ):
        self.emitter = emitter
        self.states = dict.fromkeys(units, "pending")
        self.cached: set[str] = set()
        self.retries = 0
        self.chapters_total = chapters_total
        self.chapters_completed = 0
        self.concurrency = concurrency
        self.active_requests = 0
        self.stage = "preparing"
        self.status = "running"
        self.waiting = None
        self.wait_seconds = 0.0
        self.requests_started = 0
        self.budget = None
        self.request_tokens: set[str] = set()

    def renew_requests(self):
        """Keep every live request leased, including during coordinator media IO."""
        if self.budget and self.request_tokens:
            self.budget.renew(self.request_tokens)

    def emit(self, event: str, **payload):
        counts = Counter(self.states.values())
        self.emitter.snapshot = {
            "schema": "voicebook-progress.v2",
            "status": self.status,
            "stage": self.stage,
            "unit": "speech_segment",
            "total": len(self.states),
            **{
                key: counts[key]
                for key in (
                    "completed",
                    "active",
                    "retrying",
                    "failed",
                    "cancelled",
                    "pending",
                    "queued",
                )
            },
            "retries": self.retries,
            "requests_started": self.requests_started,
            "wait_seconds": round(self.wait_seconds, 3),
            "waiting": self.waiting,
            "edge_budget": self.budget.stats() if self.budget else None,
            "cache_hits": len(self.cached),
            "active_requests": self.active_requests,
            "concurrency": self.concurrency,
            "chapters_total": self.chapters_total,
            "chapters_completed": self.chapters_completed,
            "active_units": [key for key, state in self.states.items() if state == "active"][:32],
        }
        return self.emitter.emit(event, **payload)

    def complete(self, unit: str, *, chapter_number: int, segment_index: int, result):
        if self.states[unit] == "completed":
            return
        self.states[unit] = "completed"
        if result[2]:
            self.cached.add(unit)
        self.emit(
            "unit_completed" if segment_index < 0 else "segment_completed",
            unit_id=unit,
            unit_kind="title" if segment_index < 0 else "body",
            chapter_number=chapter_number,
            segment_index=segment_index,
            cache_hit=result[2],
            fingerprint=result[1],
        )


def render_bounded(
    jobs: list[tuple[str, list[int]]],
    render: Callable[[int, Event], tuple[Path, str, bool]],
    progress: WorkProgress,
    unit_ids: list[str],
    complete: Callable[[int, tuple], None],
    cancel_file: Path | None,
    max_retries: int,
    retry_backoff: float,
    *,
    budget=None,
    steps=None,
    max_wait_seconds: float = 300,
) -> dict[int, tuple[Path, str, bool]]:
    """Coordinate work and request admission without reserving waiting threads.

    Edge step generators yield exactly one network request at a time. Every
    chunk and retry enters the persistent shared FIFO budget before submission.
    """
    pending = deque((key, indices, 0) for key, indices in jobs)
    delayed = []
    futures = {}
    rendered = {}
    generators = {}
    operations = {}
    tickets = {}
    stop = Event()
    error = None
    probe_ok = False
    progress.budget = budget
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    previous_tick = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=progress.concurrency)
    try:
        while pending or delayed or futures:
            now = time.monotonic()
            if delayed or (progress.waiting and progress.waiting["reason"] in {"shared_cooldown", "request_budget"}):
                progress.wait_seconds += now - previous_tick
            previous_tick = now
            if error is None and cancel_file and cancel_file.exists():
                error = GenerationCancelled("任务已在音频片段边界取消")
                stop.set()
                progress.status = "cancelling"
                progress.emit("cancel_requested", retryable=True)
            if error is None and progress.wait_seconds > max_wait_seconds:
                error = WaitBudgetExceeded("累计重试/冷却等待预算已耗尽，请显式恢复任务")
                stop.set()
            if budget:
                progress.renew_requests()
            if error is not None:
                for _, indices, _ in pending:
                    for index in indices:
                        progress.states[unit_ids[index]] = "cancelled"
                for _, _, indices, _, _ in delayed:
                    for index in indices:
                        progress.states[unit_ids[index]] = "cancelled"
                pending.clear()
                delayed.clear()
                for token in tickets.values():
                    budget.abandon(token)
                tickets.clear()
                progress.waiting = None
            else:
                ready = [job for job in delayed if job[0] <= now]
                delayed = [job for job in delayed if job[0] > now]
                for _, key, indices, attempt, _ in ready:
                    # A queued request may already own an older shared FIFO ticket.
                    # A retry must not jump ahead and wait on its own older ticket.
                    if probe_ok:
                        pending.append((key, indices, attempt))
                    else:
                        pending.appendleft((key, indices, attempt))
                progress.waiting = None
                limit = progress.concurrency if probe_ok else 1
                while pending and len(futures) < limit:
                    key, indices, attempt = pending[0]
                    if not probe_ok and delayed:
                        break
                    if steps and key not in operations:
                        try:
                            generator = generators.setdefault(key, steps(indices[0], stop))
                            operations[key] = next(generator)
                        except StopIteration as done:
                            generators.pop(key, None)
                            pending.popleft()
                            probe_ok = True
                            for index in indices:
                                rendered[index] = done.value
                                complete(index, done.value)
                            continue
                    if budget:
                        token = tickets.setdefault(key, str(uuid4()))
                        admission = budget.poll(token, retry=attempt > 0)
                        if not admission.admitted:
                            for index in indices:
                                progress.states[unit_ids[index]] = "queued"
                            progress.waiting = {
                                "reason": admission.reason,
                                "unit_id": unit_ids[indices[0]],
                                "retry_count": attempt,
                                "next_request_at": _utc(admission.next_at),
                            }
                            progress.status = "cooling_down" if admission.reason == "shared_cooldown" else "rate_queued"
                            break
                        tickets.pop(key)
                    else:
                        token = None
                    pending.popleft()
                    if steps:
                        operation = operations[key]
                    else:

                        def operation(index=indices[0]):
                            return render(index, stop)

                    def admitted_request(operation=operation, token=token):
                        if budget:
                            budget.start(token)
                        return operation()

                    future = pool.submit(admitted_request)
                    futures[future] = (key, indices, attempt, token)
                    if token:
                        progress.request_tokens.add(token)
                    progress.requests_started += 1
                    progress.active_requests = len(futures)
                    for index in indices:
                        progress.states[unit_ids[index]] = "active"
                    progress.status = "running"
                    progress.emit("unit_started", unit_id=unit_ids[indices[0]], request_attempt=attempt + 1)
                if progress.waiting:
                    progress.emit("waiting")
                elif delayed:
                    due, _, indices, attempt, reason = min(delayed, key=lambda item: item[0])
                    progress.status = "rate_limit_retry" if reason == "rate_limited" else "retrying"
                    progress.waiting = {
                        "reason": reason,
                        "unit_id": unit_ids[indices[0]],
                        "retry_count": attempt,
                        "next_request_at": _utc(time.time() + max(0, due - time.monotonic())),
                    }
            if not futures and not delayed and not pending:
                break
            timeout = max(0.001, next_heartbeat - time.monotonic())
            if budget:
                timeout = min(timeout, budget.renew_interval)
            if delayed and error is None:
                timeout = min(timeout, max(0.001, min(job[0] for job in delayed) - time.monotonic()))
            if delayed or (progress.waiting and progress.waiting["reason"] in {"shared_cooldown", "request_budget"}):
                timeout = min(timeout, max(0.001, max_wait_seconds - progress.wait_seconds))
            done, _ = wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
            if not futures:
                stop.wait(timeout)
            for future in done:
                key, indices, attempt, token = futures.pop(future)
                progress.active_requests = len(futures)
                try:
                    result = future.result()
                    if budget:
                        budget.finish(token)
                        progress.request_tokens.discard(token)
                        token = None
                    if steps:
                        operations.pop(key)
                        if error is not None:
                            generators.pop(key).close()
                            for index in indices:
                                progress.states[unit_ids[index]] = "cancelled"
                            continue
                        try:
                            operations[key] = next(generators[key])
                        except StopIteration as done:
                            result = done.value
                            generators.pop(key)
                        else:
                            pending.append((key, indices, attempt))
                            continue
                except Exception as exc:
                    info = error_info(exc)
                    if budget and token:
                        budget.finish(token, info)
                        progress.request_tokens.discard(token)
                    if key in generators:
                        generators.pop(key).close()
                    operations.pop(key, None)
                    if error is None and info.retryable and attempt < max_retries:
                        delay = (
                            info.retry_after
                            if info.retry_after is not None
                            else random.uniform(
                                min(60.0, retry_backoff * 2**attempt), min(60.0, retry_backoff * 2**attempt) * 1.5
                            )
                        )
                        delay = max(0.0, delay)
                        delayed.append((time.monotonic() + delay, key, indices, attempt + 1, info.reason))
                        for index in indices:
                            progress.states[unit_ids[index]] = "retrying"
                        progress.retries += 1
                        progress.status = "rate_limit_retry" if info.reason == "rate_limited" else "retrying"
                        progress.waiting = {
                            "reason": info.reason,
                            "unit_id": unit_ids[indices[0]],
                            "retry_count": attempt + 1,
                            "next_request_at": _utc(time.time() + delay),
                        }
                        progress.emit(
                            "unit_retrying",
                            unit_id=unit_ids[indices[0]],
                            code=type(exc).__name__,
                            reason=info.reason,
                            http_status=info.http_status,
                            retryable=True,
                            request_attempt=attempt + 1,
                            retry_in_seconds=delay,
                        )
                    else:
                        for index in indices:
                            progress.states[unit_ids[index]] = (
                                "cancelled" if error or isinstance(exc, GenerationCancelled) else "failed"
                            )
                        if error is None:
                            error = exc
                            stop.set()
                            if isinstance(exc, GenerationCancelled):
                                progress.status = "cancelling"
                                progress.emit("cancel_requested", retryable=True)
                            else:
                                progress.emit(
                                    "unit_failed",
                                    unit_id=unit_ids[indices[0]],
                                    code=type(exc).__name__,
                                    reason=info.reason,
                                    http_status=info.http_status,
                                    retryable=info.retryable,
                                )
                else:
                    probe_ok = True
                    if error is None:
                        progress.status = "retrying" if delayed else "running"
                        if not delayed:
                            progress.waiting = None
                    for index in indices:
                        rendered[index] = result
                        complete(index, result)
            if time.monotonic() >= next_heartbeat:
                progress.emit("heartbeat")
                next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        if error is not None:
            raise error
        return rendered
    finally:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        for generator in generators.values():
            generator.close()
        if budget:
            for token in tickets.values():
                budget.abandon(token)
            for future, (_, _, _, token) in futures.items():
                try:
                    future.result()
                except Exception as exc:
                    budget.finish(token, error_info(exc))
                else:
                    budget.finish(token)
        progress.request_tokens.clear()
