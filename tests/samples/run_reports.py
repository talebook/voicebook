"""批量对 tests/samples/*.txt 跑说话人识别，生成 Markdown 报告与统计

用法: uv run python tests/samples/run_reports.py
输出: tests/samples/reports/<书名>.md
"""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from book2audio.attribution import Attributor  # noqa: E402
from book2audio.parser import split_chapters  # noqa: E402
from book2audio.profile import assign_voices, build_profiles  # noqa: E402
from book2audio.report import write_report  # noqa: E402

SAMPLES = Path(__file__).parent
REPORTS = SAMPLES / "reports"
REPORTS.mkdir(exist_ok=True)


def main():
    att = Attributor(csi_model_dir=ROOT / "models/csi-v1")
    print(f"{'样本':　<9} {'对白':>3} {'已归属':>3} {'未识别':>3} {'角色':>3}  方法分布")
    for f in sorted(SAMPLES.glob("*.txt")):
        att.names = set()  # 每本书独立角色表（复用已加载的模型）
        text = f.read_text(encoding="utf-8")
        chapters = split_chapters(text)
        ch = chapters[0]
        quotes = att.attribute(ch.content)
        speakers = {q.speaker for q in quotes if q.speaker}
        profiles = build_profiles(ch.content, speakers)
        voices = assign_voices(profiles)
        write_report(f.stem, chapters, {ch.num: quotes}, profiles, voices,
                     REPORTS / f"{f.stem}.md")
        dia = [q for q in quotes if q.kind == "dialogue"]
        ok = [q for q in dia if q.speaker]
        methods = Counter(q.method for q in dia)
        mstr = " ".join(f"{m}:{c}" for m, c in methods.most_common())
        print(f"{f.stem:　<9} {len(dia):>4} {len(ok):>4} {len(dia)-len(ok):>4} "
              f"{len(att.names):>4}  {mstr}")


if __name__ == "__main__":
    main()
