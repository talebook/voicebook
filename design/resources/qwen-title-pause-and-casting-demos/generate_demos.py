#!/usr/bin/env python3
"""Generate the six fixed-text Qwen casting demos sequentially."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPTS = (
    "old-man-and-sea-a",
    "old-man-and-sea-b",
    "his-country-a",
    "his-country-b",
    "sky-walker-a",
    "sky-walker-b",
)


def main() -> None:
    for stem in SCRIPTS:
        script = HERE / f"{stem}.script"
        output = HERE / f"{stem}.mp4"
        print(f"\n=== generating {stem} ===", flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "book2audio",
                "--from-script",
                str(script),
                "--output",
                str(output),
                "--engine",
                "qwen",
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    main()
