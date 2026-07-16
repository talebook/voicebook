import argparse
from pathlib import Path

from .pipeline import run, run_from_script


def parse_range(s: str) -> range:
    if "-" in s:
        a, b = s.split("-", 1)
        return range(int(a), int(b) + 1)
    return range(int(s), int(s) + 1)


def main():
    p = argparse.ArgumentParser(prog="book2audio", description="小说TXT转有声书")
    p.add_argument("--input", "-i", type=Path, help="小说TXT文件（--from-script 时可省略）")
    p.add_argument("--chapters", "-c", default="1-3", help="章节范围，如 1-3 或 5")
    p.add_argument("--output", "-o", type=Path, required=True,
                   help="输出路径：.mp4=有声书 / .md=只读报告 / .script=可编辑配音脚本")
    p.add_argument("--from-script", type=Path,
                   help="从人工校正后的配音脚本(.script)直接合成，跳过识别")
    p.add_argument("--keep-temp", action="store_true", help="保留中间音频文件")
    p.add_argument("--multi-voice", action="store_true",
                   help="按角色画像分配音色（说话人识别+L3画像，需 models/csi-v1 可获得最佳归属）")
    p.add_argument("--engine", default="edge", choices=["edge", "qwen"],
                   help="TTS引擎：edge(快/云)；qwen(qwen3ttsai.com，角色系统音色丰富)")
    args = p.parse_args()

    if args.from_script:
        run_from_script(args.from_script, args.output, engine=args.engine, keep_temp=args.keep_temp)
        return
    if not args.input:
        p.error("需要 --input/-i（或用 --from-script）")
    run(args.input, args.output, parse_range(args.chapters), args.keep_temp,
        multi_voice=args.multi_voice, engine=args.engine)


if __name__ == "__main__":
    main()
