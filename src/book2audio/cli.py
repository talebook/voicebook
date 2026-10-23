"""voicebook-tool 命令行入口。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

from .machine import GenerationCancelled, ProgressEmitter, check_cancelled
from .previews import preview_catalog
from .tool_pipeline import DEFAULT_ENGINE, convert_book, generate_audio, inspect_book


def _existing_csi(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    default = Path("models/csi-v1")
    return default if default.exists() else None


def _installed_version() -> str:
    try:
        return package_version("voicebook-tool")
    except PackageNotFoundError:
        return "0+unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicebook-tool",
        description="将 EPUB/TXT 转换为多角色分章节 MP3",
    )
    parser.add_argument("--version", action="version", version=f"voicebook-tool {_installed_version()}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser("inspect", help="识别书籍并生成可编辑的 book.script")
    inspect_parser.add_argument("book", type=Path, help=".epub 或 .txt 书籍")
    inspect_parser.add_argument("-o", "--output", type=Path, required=True, help="输出 .script 文件")
    inspect_parser.add_argument("--chapters", help="章节选择，例如 1,3,8-12（默认全书）")
    inspect_parser.add_argument("--csi-model", help="CSI 模型目录；默认检测 models/csi-v1")
    _add_machine_options(inspect_parser, include_resume=False)

    generate_parser = subcommands.add_parser("generate", help="从 book.script 生成章节 MP3")
    generate_parser.add_argument("script", type=Path, help="voicebook-script v1 文件")
    generate_parser.add_argument("-o", "--output", type=Path, required=True, help="输出目录")
    _add_generation_options(generate_parser)

    convert_parser = subcommands.add_parser("convert", help="inspect + generate 一步完成")
    convert_parser.add_argument("book", type=Path, help=".epub 或 .txt 书籍")
    convert_parser.add_argument("-o", "--output", type=Path, required=True, help="输出目录")
    _add_generation_options(convert_parser)
    convert_parser.add_argument("--csi-model", help="CSI 模型目录；默认检测 models/csi-v1")

    models = subcommands.add_parser("models", help="管理可选模型")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    download = model_commands.add_parser("download", help="下载模型")
    download.add_argument("model", choices=["csi"])
    download.add_argument("-o", "--output", type=Path, default=Path("models/csi-v1"))

    voices = subcommands.add_parser("voices", help="输出结构化音色与十场景试听目录")
    voices.add_argument("--engine", choices=["qwen3tts", "edgetts", "all"], default="all")
    voices.add_argument("--include-paths", action="store_true", help="包含本机试听资产绝对路径")
    voices.add_argument("--format", choices=["json", "human"], default="human")
    return parser


def _add_generation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        choices=["qwen3tts", "edgetts"],
        default=DEFAULT_ENGINE,
        help="TTS 引擎（默认 edgetts）",
    )
    parser.add_argument("--chapters", help="章节选择，例如 1,3,8-12（默认全书）")
    parser.add_argument("--force", action="store_true", help="忽略片段缓存并重新合成")
    parser.add_argument(
        "--concurrency",
        type=int,
        help="单本请求并发上限 1–32（Edge 默认 1，Qwen 默认 2）",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="瞬时错误的额外重试次数 0–10（默认 2）",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=1.0,
        help="重试退避基数 0–30 秒（默认 1）",
    )
    parser.add_argument("--max-wait-seconds", type=float, default=300, help="累计重试/冷却/预算等待上限（默认 300 秒）")
    parser.add_argument("--edge-budget-path", type=Path, help="多进程共用的 Edge SQLite 预算文件")
    parser.add_argument("--edge-interval", type=float, default=5, help="Edge 共享请求启动间隔（默认 5 秒）")
    parser.add_argument("--edge-max-concurrency", type=int, default=1, help="Edge 跨任务连接上限（默认 1）")
    parser.add_argument("--edge-request-limit", type=int, default=0, help="共享窗口请求预算（0 表示不设配额）")
    parser.add_argument("--edge-window-seconds", type=float, default=3600, help="请求预算窗口秒数（默认 3600）")
    parser.add_argument("--edge-cooldown-seconds", type=float, default=30, help="连续瞬时失败共享冷却秒数（默认 30）")
    _add_machine_options(parser, include_resume=True)


def _add_machine_options(parser: argparse.ArgumentParser, *, include_resume: bool) -> None:
    parser.add_argument(
        "--progress-format",
        choices=["human", "jsonl"],
        default="human",
        help="进度输出格式；宿主进程使用 jsonl",
    )
    parser.add_argument(
        "--progress-version",
        type=int,
        choices=[1, 2],
        default=1,
        help="JSONL 协议版本（默认 1；新接入使用 2）",
    )
    parser.add_argument("--task-id", help="宿主任务标识；默认生成 UUID")
    parser.add_argument("--attempt-id", help="当前 CLI 尝试标识；每次调用必须唯一，默认 UUID")
    parser.add_argument("--cancel-file", type=Path, help="该文件存在时在安全边界取消")
    if include_resume:
        parser.add_argument("--resume", action="store_true", help="复用匹配的已完成章节和片段缓存")


def _download_csi(output: Path) -> None:
    from huggingface_hub import snapshot_download

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 CSI 模型到 {output} ...")
    try:
        snapshot_download(
            repo_id="Warma10032/chinese-roberta-wwm-ext-large-csi-v1",
            local_dir=output,
        )
    except Exception as exc:
        raise RuntimeError(f"CSI 模型下载失败：{exc}") from exc
    print(f"完成：{output}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    progress = None
    machine_output = getattr(args, "progress_format", "human") == "jsonl"
    if args.command in {"inspect", "generate", "convert"}:
        options = {
            "version": args.progress_version,
            "stream": sys.stdout if machine_output else None,
        }
        if args.task_id:
            options["task_id"] = args.task_id
        if args.attempt_id:
            options["attempt_id"] = args.attempt_id
        progress = ProgressEmitter(**options)

    def human(message: str) -> None:
        if not machine_output:
            print(message)

    try:
        if args.command == "inspect":
            if progress:
                progress.emit("phase_started", job_phase="INSPECTING")
            check_cancelled(args.cancel_file)
            script = inspect_book(
                args.book,
                args.output,
                chapters=args.chapters,
                csi_model=_existing_csi(args.csi_model),
            )
            check_cancelled(args.cancel_file)
            if progress:
                payload = {
                    "script": str(args.output),
                    "chapter_count": len(script.chapters),
                    "character_count": len(script.characters) - 1,
                }
                if script.quality_report:
                    payload["normalization"] = script.quality_report
                progress.emit("completed", **payload)
            human(f"完成：{args.output}（{len(script.chapters)} 章，{len(script.characters) - 1} 个角色）")
            return 0
        if args.command == "generate":
            human("提示：所选章节正文会发送到第三方云端 TTS 服务。")
            outputs = generate_audio(
                args.script,
                args.output,
                engine=args.engine,
                chapters=args.chapters,
                force=args.force,
                progress=progress,
                cancel_file=args.cancel_file,
                resume=args.resume,
                concurrency=args.concurrency,
                max_retries=args.max_retries,
                retry_backoff=args.retry_backoff,
                max_wait_seconds=args.max_wait_seconds,
                edge_budget_path=args.edge_budget_path,
                edge_interval=args.edge_interval,
                edge_max_concurrency=args.edge_max_concurrency,
                edge_request_limit=args.edge_request_limit,
                edge_window_seconds=args.edge_window_seconds,
                edge_cooldown_seconds=args.edge_cooldown_seconds,
            )
            for output in outputs:
                human(f"完成：{output}")
            return 0
        if args.command == "convert":
            human("提示：所选章节正文会发送到第三方云端 TTS 服务。")
            outputs = convert_book(
                args.book,
                args.output,
                engine=args.engine,
                chapters=args.chapters,
                force=args.force,
                csi_model=_existing_csi(args.csi_model),
                progress=progress,
                cancel_file=args.cancel_file,
                resume=args.resume,
                concurrency=args.concurrency,
                max_retries=args.max_retries,
                retry_backoff=args.retry_backoff,
                max_wait_seconds=args.max_wait_seconds,
                edge_budget_path=args.edge_budget_path,
                edge_interval=args.edge_interval,
                edge_max_concurrency=args.edge_max_concurrency,
                edge_request_limit=args.edge_request_limit,
                edge_window_seconds=args.edge_window_seconds,
                edge_cooldown_seconds=args.edge_cooldown_seconds,
            )
            for output in outputs:
                human(f"完成：{output}")
            return 0
        if args.command == "models" and args.models_command == "download":
            _download_csi(args.output)
            return 0
        if args.command == "voices":
            catalog = preview_catalog(
                None if args.engine == "all" else args.engine,
                include_paths=args.include_paths,
            )
            if args.format == "json":
                print(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")))
            else:
                for voice in catalog["voices"]:
                    state = "十场景可试听" if voice["preview_available"] else "试听资产未安装"
                    print(f"{voice['engine']}\t{voice['voice_id']}\t{voice['gender']}\t{state}")
            return 0
    except GenerationCancelled as exc:
        if progress and progress.last_event != "cancelled":
            progress.emit("cancelled", message=str(exc), retryable=True)
        print(f"取消：{exc}", file=sys.stderr)
        return 3
    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
    ) as exc:
        if progress and progress.last_event != "failed":
            progress.emit("failed", code=type(exc).__name__, message=str(exc), retryable=True)
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
