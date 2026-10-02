"""Provider metadata without exposing text, response bodies or request URLs."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import requests
from aiohttp import ClientConnectionError


def parse_retry_after(value, now: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        delay = float(value)
        return delay if math.isfinite(delay) and delay >= 0 else None
    except (TypeError, ValueError):
        try:
            when = parsedate_to_datetime(str(value))
            if when.tzinfo is None:
                return None
            return max(0.0, when.timestamp() - (time.time() if now is None else now))
        except (TypeError, ValueError, OverflowError):
            return None


@dataclass(frozen=True)
class ErrorInfo:
    retryable: bool = False
    retry_after: float | None = None
    http_status: int | None = None
    reason: str = "generation_error"


def error_info(error: BaseException) -> ErrorInfo:
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(current, "http_status", None) or getattr(current, "status", None)
        headers = getattr(current, "headers", None)
        if response is not None:
            status = getattr(response, "status_code", status)
            headers = getattr(response, "headers", headers)
        if isinstance(status, int):
            retryable = getattr(current, "retryable", status == 429 or 500 <= status < 600)
            return ErrorInfo(
                bool(retryable),
                parse_retry_after(headers.get("Retry-After") or headers.get("retry-after"))
                if headers
                else parse_retry_after(getattr(current, "retry_after", None)),
                status,
                getattr(current, "reason", "rate_limited" if status == 429 else "provider_error"),
            )
        if hasattr(current, "retryable"):
            return ErrorInfo(
                bool(current.retryable),
                parse_retry_after(getattr(current, "retry_after", None)),
                None,
                getattr(current, "reason", "provider_error"),
            )
        if isinstance(
            current, (TimeoutError, ConnectionError, requests.Timeout, requests.ConnectionError, ClientConnectionError)
        ):
            return ErrorInfo(True, None, None, "network_error")
        current = current.__cause__ or current.__context__
    return ErrorInfo()


def safe_error(error: BaseException) -> str:
    info = error_info(error)
    suffix = f"HTTP {info.http_status}" if info.http_status else type(error).__name__
    return f"生成失败（{suffix}，{info.reason}）"
