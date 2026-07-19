"""面向宿主进程的稳定 JSONL 事件协议。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


PROGRESS_SCHEMA = "voicebook-progress.v1"


class GenerationCancelled(RuntimeError):
    """生成任务在安全边界响应了取消信号。"""


@dataclass
class ProgressEmitter:
    stream: IO[str] = field(default_factory=lambda: sys.stdout)
    sequence: int = 0
    last_event: str = ""

    def emit(self, event: str, **payload: Any) -> dict[str, Any]:
        self.sequence += 1
        self.last_event = event
        message = {
            "schema": PROGRESS_SCHEMA,
            "seq": self.sequence,
            "event": event,
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            **payload,
        }
        self.stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.stream.flush()
        return message


def check_cancelled(cancel_file: Path | None) -> None:
    if cancel_file and cancel_file.exists():
        raise GenerationCancelled("任务已在音频片段边界取消")
