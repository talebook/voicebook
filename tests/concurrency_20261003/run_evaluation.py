"""Offline TB-234 benchmark and progress demonstration; never calls a provider."""

from __future__ import annotations

import html
import io
import json
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from audio_markers import validate_audio_content, write_marker

from book2audio.edge_budget import EdgeBudget
from book2audio.machine import GenerationCancelled, ProgressEmitter
from book2audio.provider_errors import ErrorInfo
from book2audio.script import (
    ScriptChapter,
    ScriptCharacter,
    ScriptSegment,
    VoicebookScript,
    write_voicebook_script,
)
from book2audio.tool_pipeline import generate_audio
from book2audio.tts import QwenTTSAPIError
from book2audio.work import WaitBudgetExceeded

HERE = Path(__file__).resolve().parent


class SimulatedEngine:
    def __init__(self, *, failure=None, cancel=None):
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0
        self.calls = []
        self.attempts = {}
        self.failure = failure
        self.cancel = cancel

    def synthesize(self, text, voice, engine, output):
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            self.calls.append(text)
            self.attempts[text] = self.attempts.get(text, 0) + 1
            attempt = self.attempts[text]
        try:
            # Slow and fast requests deterministically finish out of script order.
            time.sleep(0.35 if text.endswith("段0") else 0.12)
            if self.failure == "retry" and text.endswith("段1") and attempt == 1:
                raise QwenTTSAPIError("模拟 HTTP 429", retryable=True, retry_after=0.02, http_status=429)
            if self.failure == "permanent" and text == "章2段1":
                raise QwenTTSAPIError("模拟 HTTP 403", retryable=False, http_status=403)
            if self.cancel and text == "章1段1":
                self.cancel.touch()
            write_marker(text, output)
        finally:
            with self.lock:
                self.active -= 1


def run_case(
    root, name, concurrency, *, failure=None, cancel=False, resume=False, budget=None, cancel_wait=False, max_wait=300
):
    output = root / ("recovery" if name in {"partial_failure", "resume"} else name)

    class Stream(io.StringIO):
        def write(self, value):
            if cancel_wait and json.loads(value).get("snapshot", {}).get("status") == "cooling_down":
                cancel_file.touch()
            return super().write(value)

    stream = Stream()
    cancel_file = root / f"{name}.signal" if cancel or cancel_wait else None
    synth = SimulatedEngine(failure=failure, cancel=cancel_file)
    started = time.monotonic()
    status = "completed"
    try:
        files = generate_audio(
            root / "book.script",
            output,
            synthesizer=synth,
            engine="edgetts" if budget else "qwen3tts",
            edge_budget=budget,
            max_wait_seconds=max_wait,
            progress=ProgressEmitter(stream, version=2, task_id="offline-demo-book"),
            concurrency=concurrency,
            max_retries=2,
            retry_backoff=0.02,
            cancel_file=cancel_file,
            resume=resume,
        )
    except GenerationCancelled:
        status = "cancelled"
        files = []
    except (QwenTTSAPIError, WaitBudgetExceeded):
        status = "failed"
        files = []
    elapsed = round(time.monotonic() - started, 3)
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    manifest = json.loads((output / "manifest.v2.json").read_text())
    latest = json.loads((output / ".voicebook/progress.v2.json").read_text())
    assert latest == rows[-1]
    assert synth.active == 0 and synth.maximum <= concurrency
    for row in rows:
        value = row["snapshot"]
        assert value["total"] == sum(
            value[key] for key in ("completed", "pending", "active", "retrying", "failed", "cancelled", "queued")
        )
    audio_content = [
        {"chapter": record["number"], **validate_audio_content(
            output / record["audio"],
            [f"标题{record['number']}", *(f"章{record['number']}段{i}" for i in range(4))],
        )}
        for record in manifest["chapters"]
    ]
    if status == "completed":
        assert [path.name for path in files] == ["0001.mp3", "0002.mp3"]
        assert manifest["status"] == "completed" and latest["snapshot"]["completed"] == 10
        for number in (1, 2):
            timeline = json.loads((output / f"timelines/{number:04d}.json").read_text())
            assert [item["text"] for item in timeline["segments"]] == [f"章{number}段{i}" for i in range(4)]
    else:
        assert manifest["status"] == status
        assert not any(row["event"] == "completed" for row in rows)
    return {
        "case": name,
        "concurrency": concurrency,
        "maximum_requests": synth.maximum,
        "elapsed_seconds": elapsed,
        "provider_calls": len(synth.calls),
        "status": status,
        "audio_content": audio_content,
        "final_snapshot": latest["snapshot"],
        "events": rows,
    }


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = VoicebookScript(
            title="两章模拟书",
            characters=[ScriptCharacter("旁白", "旁白", gender="男")],
            chapters=[
                ScriptChapter(n, f"标题{n}", [ScriptSegment("旁白", f"章{n}段{i}") for i in range(4)]) for n in (1, 2)
            ],
        )
        write_voicebook_script(script, root / "book.script")
        results = [
            run_case(root, "serial", 1),
            run_case(root, "parallel", 3),
            run_case(root, "rate_limit_retry", 3, failure="retry"),
            run_case(root, "cancel", 3, cancel=True),
            run_case(root, "partial_failure", 3, failure="permanent"),
            run_case(root, "resume", 3, resume=True),
        ]
        edge = EdgeBudget(root / "shared.sqlite", interval=0.03, concurrency=1)
        results.append(run_case(root, "edge_shared_limit", 3, budget=edge))
        assert edge.poll("upstream").admitted
        edge.start("upstream")
        edge.finish("upstream", ErrorInfo(True, 60, 429, "rate_limited"))
        results.append(run_case(root, "edge_cooldown_cancel", 3, budget=edge, cancel_wait=True))
        results.append(run_case(root, "edge_wait_budget_exhausted", 3, budget=edge, max_wait=0.03))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "offline synthetic PCM WAV",
        "unit": "speech_segment",
        "units": 10,
        "chapters": 2,
        "cases": results,
    }
    (HERE / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summaries = "".join(
        f"<tr><td>{case['case']}</td><td>{case['concurrency']}</td><td>{case['maximum_requests']}</td>"
        f"<td>{case['elapsed_seconds']}</td><td>{case['provider_calls']}</td><td>{case['status']}</td>"
        f"<td>{case['final_snapshot']['completed']}/10</td><td>{case['final_snapshot']['retries']}</td></tr>"
        for case in results
    )
    traces = []
    for case in results:
        rows = []
        for event in case["events"]:
            value = event["snapshot"]
            rows.append(
                f"<tr><td>{event['seq']}</td><td>{html.escape(event['event'])}</td>"
                f"<td>{html.escape(event.get('unit_id', ''))}</td><td>{value['stage']}</td><td>{value['status']}</td>"
                f"<td>{value['completed']}/{value['total']}</td><td>{value['active_requests']}</td>"
                f"<td>{value['retrying']}</td><td>{value['failed']}</td>"
                f"<td>{html.escape((value.get('waiting') or {}).get('reason') or event.get('reason') or '')}</td>"
                f"<td>{html.escape((value.get('waiting') or {}).get('next_request_at') or '')}</td></tr>"
            )
        traces.append(
            f"<details><summary>{case['case']} · {case['status']} · 尝试 {case['events'][0]['attempt_id']}</summary>"
            "<div class='scroll'><table><thead><tr><th>seq</th><th>事件</th><th>单元</th><th>阶段</th><th>状态</th>"
            "<th>完成片段</th><th>活动请求</th><th>退避</th><th>失败</th><th>等待原因</th><th>计划请求时间 UTC</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div></details>"
        )
    audio_checks = "".join(
        f"<tr><td>{case['case']}</td><td>{check['chapter']}</td>"
        f"<td>{html.escape(' → '.join(check['observed']))}</td>"
        f"<td>{html.escape(str(check['frequencies_hz']))}</td>"
        f"<td>{html.escape(str(check['marker_seconds']))}</td></tr>"
        for case in results for check in case["audio_content"]
    )
    report = (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TB-234 单本并发与真实进度模拟验证</title><style>body{font:16px/1.65 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#243447;background:#f4f7fb}
table{border-collapse:collapse;background:white;width:100%;font-size:14px}td,th{padding:8px 12px;text-align:left;border-bottom:1px solid #dce4ed}th{background:#e4edf7}details{margin:18px 0;background:white;padding:12px;border-radius:8px}summary{cursor:pointer;font-weight:600}.scroll{overflow:auto}code{background:#e4edf7;padding:2px 5px}</style>
<h1>TB-234 单本并发与真实进度模拟验证</h1><p>同一本两章脚本：2 个标题 + 8 个正文片段。模拟引擎只生成本地 WAV，ffmpeg 执行真实规范化、合成和 MP3 校验；没有第三方语音调用。</p>
<p>慢请求 350ms，其余请求 120ms。并发对照使用可控模拟引擎；Edge 场景另加共享并发 1、间隔 30ms 的加速测试预算（生产默认 1、5 秒）。首个缺失片段探测成功后才并发。下表包含完整音频处理耗时，不能外推真实供应商加速倍数。</p>
<div class="scroll"><table><thead><tr><th>场景</th><th>配置上限</th><th>实测上限</th><th>耗时/秒</th><th>模拟请求数</th><th>状态</th><th>完成片段</th><th>重试数</th></tr></thead><tbody>"""
        + summaries
        + """</tbody></table></div>
<p>所有成功场景已校验章节顺序、时间轴正文顺序、10 个单元无遗漏、快照分区计数和持久化文件。失败与取消场景没有 completed 事件；恢复尝试从 0 开始重新计数并复用经过校验的章节和缓存。</p>
<h2>最终 MP3 内容顺序</h2><p>每个标题/正文片段使用唯一的 500–2300Hz 音调，长 240ms。独立解码最终 MP3，以 20ms 帧的 Goertzel 能量识别实际音调序列，并检查每次出现的时长，覆盖相邻重复。判定不读取时间轴文字或缓存文件名；部分失败后保留的章节和恢复后的全部章节同样验证。</p>
<div class='scroll'><table><thead><tr><th>场景</th><th>章节</th><th>解码得到的内容顺序</th><th>音调 Hz</th><th>各片段秒数</th></tr></thead><tbody>"""
        + audio_checks
        + """</tbody></table></div>
<p><strong>完成片段达到 10/10 时仍可处于 assembling/finalizing。</strong>只有最终 manifest 写入成功后才完成。Talebook 页面接入和全链路 QA 尚待后续任务。</p>
<h2>完整事件演示</h2><p>展开场景查看乱序返回、计数变化、阶段切换、429 退避、取消、部分失败、新尝试恢复、Edge 共享队列、冷却取消与等待预算耗尽。这里展示工作量，不生成虚假的耗时百分比。</p>"""
        + "".join(traces)
        + "</html>"
    )
    (HERE / "report.html").write_text(report, encoding="utf-8")
    print(
        json.dumps(
            [
                {key: value for key, value in case.items() if key not in {"events", "final_snapshot"}}
                for case in results
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
