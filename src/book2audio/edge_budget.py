"""One persistent FIFO request/connection budget shared by local processes."""

from __future__ import annotations

import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .provider_errors import ErrorInfo

LEASE_SECONDS = 120.0


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: str | None = None
    next_at: float | None = None


class EdgeBudget:
    def __init__(
        self,
        path: Path,
        *,
        interval: float = 5.0,
        concurrency: int = 1,
        request_limit: int = 0,
        window_seconds: float = 3600,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ):
        if not 0 <= interval <= 3600 or not 1 <= concurrency <= 32:
            raise ValueError("Edge 请求间隔须为 0–3600 秒、共享并发须为 1–32")
        if (
            not all(math.isfinite(value) for value in (window_seconds, cooldown_seconds))
            or request_limit < 0
            or window_seconds <= 0
            or failure_threshold < 1
            or cooldown_seconds < 0
        ):
            raise ValueError("Edge 预算或冷却配置无效")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        config = (interval, concurrency, request_limit, window_seconds, failure_threshold, cooldown_seconds)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (
                    id INTEGER PRIMARY KEY CHECK(id=1), interval REAL, capacity INTEGER,
                    request_limit INTEGER, window_seconds REAL, failure_threshold INTEGER, cooldown_seconds REAL,
                    next_start REAL DEFAULT 0, cooldown_until REAL DEFAULT 0, streak INTEGER DEFAULT 0,
                    window_start REAL DEFAULT 0, window_requests INTEGER DEFAULT 0,
                    requests INTEGER DEFAULT 0, rate_limits INTEGER DEFAULT 0,
                    retries INTEGER DEFAULT 0, cooldowns INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS queue (
                    position INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE, expires REAL
                );
                CREATE TABLE IF NOT EXISTS active (token TEXT PRIMARY KEY, expires REAL, started INTEGER DEFAULT 0);
            """)
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO state(id,interval,capacity,request_limit,window_seconds,failure_threshold,cooldown_seconds) VALUES(1,?,?,?,?,?,?)",
                config,
            )
            stored = db.execute(
                "SELECT interval,capacity,request_limit,window_seconds,failure_threshold,cooldown_seconds FROM state"
            ).fetchone()
            if tuple(stored) != config:
                raise ValueError("同一 Edge 共享预算的配置不一致；请在所有 worker 中统一配置")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def poll(self, token: str, *, retry: bool = False) -> Admission:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM queue WHERE expires <= ?", (now,))
            db.execute("DELETE FROM active WHERE expires <= ?", (now,))
            db.execute("INSERT OR IGNORE INTO queue(token,expires) VALUES(?,?)", (token, now + LEASE_SECONDS))
            db.execute("UPDATE queue SET expires=? WHERE token=?", (now + LEASE_SECONDS, token))
            state = db.execute("SELECT * FROM state").fetchone()
            if now >= state["window_start"] + state["window_seconds"]:
                db.execute("UPDATE state SET window_start=?,window_requests=0", (now,))
                window_start, window_requests = now, 0
            else:
                window_start, window_requests = state["window_start"], state["window_requests"]
            if state["cooldown_until"] > now:
                return Admission(False, "shared_cooldown", state["cooldown_until"])
            if state["request_limit"] and window_requests >= state["request_limit"]:
                return Admission(False, "request_budget", window_start + state["window_seconds"])
            head = db.execute("SELECT token FROM queue ORDER BY position LIMIT 1").fetchone()
            if head["token"] != token:
                return Admission(False, "fair_queue")
            if db.execute("SELECT COUNT(*) FROM active WHERE started=0").fetchone()[0]:
                return Admission(False, "starting_request")
            if db.execute("SELECT COUNT(*) FROM active").fetchone()[0] >= state["capacity"]:
                return Admission(False, "global_concurrency")
            if state["next_start"] > now:
                return Admission(False, "request_interval", state["next_start"])
            db.execute("DELETE FROM queue WHERE token=?", (token,))
            db.execute("INSERT INTO active(token,expires) VALUES(?,?)", (token, now + LEASE_SECONDS))
            db.execute(
                "UPDATE state SET next_start=?,requests=requests+1,window_requests=window_requests+1,retries=retries+?",
                (now + state["interval"], int(retry)),
            )
            return Admission(True)

    def start(self, token: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM state").fetchone()
            if not db.execute("UPDATE active SET started=1 WHERE token=?", (token,)).rowcount:
                raise RuntimeError("Edge 请求预算租约已失效")
            db.execute("UPDATE state SET next_start=MAX(next_start,?)", (time.time() + state["interval"],))

    def renew(self, tokens):
        with self.connect() as db:
            db.executemany(
                "UPDATE active SET expires=? WHERE token=?", [(time.time() + LEASE_SECONDS, token) for token in tokens]
            )

    def abandon(self, token: str):
        with self.connect() as db:
            db.execute("DELETE FROM queue WHERE token=?", (token,))

    def finish(self, token: str, info: ErrorInfo | None = None):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM active WHERE token=?", (token,))
            state = db.execute("SELECT * FROM state").fetchone()
            if info is None:
                db.execute("UPDATE state SET streak=0")
                return
            if not info.retryable:
                return
            streak = state["streak"] + 1
            cooldown = max(state["cooldown_until"], now + (info.retry_after or 0))
            opened = streak >= state["failure_threshold"]
            if opened:
                cooldown = max(cooldown, now + state["cooldown_seconds"])
            db.execute(
                "UPDATE state SET streak=?,cooldown_until=?,rate_limits=rate_limits+?,cooldowns=cooldowns+?",
                (streak, cooldown, int(info.http_status == 429), int(opened)),
            )

    def stats(self):
        with self.connect() as db:
            state = dict(db.execute("SELECT * FROM state").fetchone())
            return {key: state[key] for key in ("requests", "rate_limits", "retries", "cooldowns", "cooldown_until")}
