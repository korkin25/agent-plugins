#!/usr/bin/env python3
"""text-14: references.txt holds the 12 distinct works formatted, sorted and numbered per style.md, compared line by line."""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Fail(Exception):
    """The output breaks a stated constraint; the message is the reason."""


def read_text(workdir: Path, name: str) -> str:
    path = workdir / name
    if not path.is_file():
        raise Fail(f"{name} is missing")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Fail(f"{name} is not UTF-8 text")
    return text.lstrip("﻿")


def read_json(workdir: Path, name: str):
    text = read_text(workdir, name)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise Fail(f"{name} is not valid JSON: {exc}")


def collapse(text: str) -> str:
    """Every run of whitespace, line breaks included, becomes one space."""
    return " ".join(text.split())

def check(workdir: Path) -> None:
    got = [line.rstrip() for line in read_text(workdir, "references.txt").splitlines() if line.strip()]
    want = [line for line in (HERE / "expected.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not got:
        raise Fail("references.txt has no references")
    for n, (g, w) in enumerate(zip(got, want), start=1):
        if g != w:
            hint = ""
            if g.replace("-", "–") == w:
                hint = " (page ranges need an en dash)"
            raise Fail(f"reference line {n}: got {g!r}, expected {w!r}{hint}")
    if len(got) != len(want):
        raise Fail(f"{len(got)} references, expected {len(want)}")


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: check.py WORKDIR")
        return 2
    try:
        check(Path(argv[1]))
    except Fail as exc:
        print(exc)
        return 1
    except Exception as exc:  # an unexpected output shape is a fail, never a crash
        print(f"output could not be checked: {type(exc).__name__}: {exc}")
        return 1
    print("pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
