#!/usr/bin/env python3
"""text-09: pismo_ispr.txt equals the letter after the six numbered edits, whitespace collapsed."""
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
    got = collapse(read_text(workdir, "pismo_ispr.txt"))
    want = collapse((HERE / "expected.txt").read_text(encoding="utf-8"))
    if got == want:
        return
    if not got:
        raise Fail("pismo_ispr.txt is empty")
    pos = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
    raise Fail(f"text differs from the expected letter at character {pos}: "
               f"got {got[max(0, pos - 30):pos + 30]!r}, expected {want[max(0, pos - 30):pos + 30]!r}")


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
