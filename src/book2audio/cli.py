"""voicebook-tool 命令行入口。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .tool_pipeline import DEFAULT_ENGINE, convert_book, generate_audio, inspect_book


def _existing_csi(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    default = Path("models/csi-v1")
    return default if default.exists() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicebook-tool",
        description="将 EPUB/TXT 转换为多角色分章节 MP3",
    )
    parser.add_argument("--version", action="version", version="voicebook-tool 0.2.0")
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subcommands.add_parser("inspect", help="识别书籍并生成可编辑的 book.script")
    inspect_parser.add_argument("book", type=Path, help=".epub 或 .txt 书籍")
    inspect_parser.add_argument("-o", "--output", type=Path, required=True, help="输出 .script 文件")
    inspect_parser.add_argument("--chapters", help="章节选择，例如 1,3,8-12（默认全书）")
    inspect_parser.add_argument("--csi-model", help="CSI 模型目录；默认检测 models/csi-v1")

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
    return parser


def _add_generation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        choices=["qwen3tts", "edgetts"],
        default=DEFAULT_ENGINE,
        help="TTS 引擎（默认 edgetts）",
    )
    parser.add_argument("--chapters", help="章节选择，例如 1,3,8-12（默认全书）")
    parser.add_argument("--combine", action="store_true", help="额外输出一份全书合并 MP3")
    parser.add_argument("--force", action="store_true", help="忽略片段缓存并重新合成")


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
    try:
        if args.command == "inspect":
            script = inspect_book(
                args.book,
                args.output,
                chapters=args.chapters,
                csi_model=_existing_csi(args.csi_model),
            )
            print(f"完成：{args.output}（{len(script.chapters)} 章，{len(script.characters) - 1} 个角色）")
            return 0
        if args.command == "generate":
            print("提示：所选章节正文会发送到第三方云端 TTS 服务。")
            outputs = generate_audio(
                args.script,
                args.output,
                engine=args.engine,
                chapters=args.chapters,
                combine=args.combine,
                force=args.force,
            )
            for output in outputs:
                print(f"完成：{output}")
            return 0
        if args.command == "convert":
            print("提示：所选章节正文会发送到第三方云端 TTS 服务。")
            outputs = convert_book(
                args.book,
                args.output,
                engine=args.engine,
                chapters=args.chapters,
                combine=args.combine,
                force=args.force,
                csi_model=_existing_csi(args.csi_model),
            )
            for output in outputs:
                print(f"完成：{output}")
            return 0
        if args.command == "models" and args.models_command == "download":
            _download_csi(args.output)
            return 0
    except (FileNotFoundError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    parser.error("未知命令")
    return 2
if __name__ == "__main__":
    raise SystemExit(main())
