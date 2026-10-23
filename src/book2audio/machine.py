"""面向宿主进程的稳定 JSONL 事件协议。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

PROGRESS_SCHEMA = "voicebook-progress.v1"


class GenerationCancelled(RuntimeError):
    """生成任务在安全边界响应了取消信号。"""


@dataclass
class ProgressEmitter:
    stream: IO[str] | None = field(default_factory=lambda: sys.stdout)
    sequence: int = 0
    last_event: str = ""
    version: int = 1
    task_id: str = field(default_factory=lambda: str(uuid4()))
    attempt_id: str = field(default_factory=lambda: str(uuid4()))
    snapshot: dict[str, Any] | None = None
    snapshot_path: Path | None = None

    def emit(self, event: str, **payload: Any) -> dict[str, Any]:
        self.sequence += 1
        self.last_event = event
        message = {
            "schema": f"voicebook-progress.v{self.version}",
            "seq": self.sequence,
            "event": event,
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            **payload,
        }
        if self.snapshot is not None:
            message["snapshot"] = {**self.snapshot, "updated_at": message["at"]}
        if self.snapshot_path:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.snapshot_path.with_name(f".{self.snapshot_path.name}.tmp")
            temporary.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.snapshot_path)
        if self.stream is not None:
            self.stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.stream.flush()
        return message


def check_cancelled(cancel_file: Path | None) -> None:
    if cancel_file and cancel_file.exists():
        raise GenerationCancelled("任务已在音频片段边界取消")
