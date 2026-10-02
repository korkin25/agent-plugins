#!/usr/bin/env python3
"""math-01: answer.txt holds the count of n in [1, 10**6] divisible by 3 or 5 but not by 15."""
import sys
from pathlib import Path

EXPECTED = 400001


def main(workdir: Path) -> int:
    path = workdir / "answer.txt"
    if not path.is_file():
        print("answer.txt is missing")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text.isdigit():
        print(f"answer.txt is not a plain integer: {text[:40]!r}")
        return 1
    if int(text) != EXPECTED:
        print(f"wrong count {int(text)}")
        return 1
    print("pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
