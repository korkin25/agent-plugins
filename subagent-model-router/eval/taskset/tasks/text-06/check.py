#!/usr/bin/env python3
"""text-06: summary.txt is at most 60 words, states the required facts and leaves out the forbidden ones."""
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

LIMIT = 60
REQUIRED = [
    ("the incident date 2027-01-14", r"(?<!\d)2027-01-14(?!\d)"),
    ("the duration of 47 minutes", r"(?<![\d.,])47(?![\d]|[.,]\d)"),
    ("the 1,284 failed requests", r"(?<![\d.,])1[,\u00a0\u202f ]?284(?![\d]|[.,]\d)"),
    ("the engineer's surname Adeyemi", r"(?i)\badeyemi\b"),
    ("the exact phrase 'expired TLS certificate'", r"(?i)\bexpired TLS certificate\b"),
]
FORBIDDEN = [
    ("a merchant name", r"(?i)bramblewood|corvid|lumen"),
    ("the internal ticket number", r"(?i)OPS-?\s*4471|\b4471\b"),
    ("a clock time", r"\b\d{1,2}:\d{2}\b"),
    ("a clock time", r"(?i)(?<![\w.,:-])\d{1,2}(?:[:.]\d{2})?\s?[ap]\.?m(?![a-z])"),
    ("a clock time", r"(?i)(?<![\w.,:-])\d{1,2}(?:[:.h]?\d{2})?\s?(?:UTC|GMT)\b"),
]


def check(workdir: Path) -> None:
    text = read_text(workdir, "summary.txt")
    flat = collapse(text)
    words = len(text.split())
    if words == 0:
        raise Fail("summary.txt is empty")
    if words > LIMIT:
        raise Fail(f"{words} words, more than {LIMIT}")
    for label, pattern in REQUIRED:
        if not re.search(pattern, flat):
            raise Fail(f"missing {label}")
    for label, pattern in FORBIDDEN:
        if re.search(pattern, flat):
            raise Fail(f"contains {label}")


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
