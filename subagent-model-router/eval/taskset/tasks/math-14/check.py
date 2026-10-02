#!/usr/bin/env python3
"""math-14: answer.txt holds the number of rotation classes of valid 12-slot ring fillings with 4+4+4 colours."""
import re
import sys
from pathlib import Path

EXPECTED = 70


def main(workdir: Path) -> int:
    path = workdir / "answer.txt"
    if not path.is_file():
        print("answer.txt is missing")
        return 1
    text = path.read_bytes()[:4096].decode("utf-8", errors="replace").strip()
    if not re.fullmatch(r"[0-9]+", text):
        print(f"answer.txt is not a plain integer: {text[:40]!r}")
        return 1
    if int(text) != EXPECTED:
        print(f"wrong value {text[:40]}")
        return 1
    print("pass")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(Path(sys.argv[1])))
    except Exception as exc:  # a malformed workdir is a fail, never a crash
        print(f"check could not read the answer: {type(exc).__name__}")
        sys.exit(1)
