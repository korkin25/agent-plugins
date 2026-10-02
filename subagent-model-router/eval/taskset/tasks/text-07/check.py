#!/usr/bin/env python3
"""text-07: svodka.txt is at most 70 words, states the corrected figures and the required facts, and leaves out competitors, bonuses and superseded values."""
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

LIMIT = 70
REQUIRED = [
    ("the corrected revenue 48,6", r"(?<![\d,.])48[,.]6(?!\d)"),
    ("the corrected growth 12 %", r"(?<![\d,.])12(?:[,.]0)?\s?%"),
    ("the opening date 01.04.2027", r"(?<![\d.])01\.04\.2027(?!\d)"),
    ("the director's surname (stem Дорохов)", r"дорохов"),
]
NAME = ("the warehouse name (stem Восточн, capitalized as a name)", r"Восточн|ВОСТОЧН")
FORBIDDEN = [
    ("a competitor's name", r"глобус|мегаполис"),
    ("a mention of bonuses (stem преми, бонус or вознагражд)", r"преми|бонус|вознагражд"),
    ("the bonus amount 1,2 млн руб.", r"(?<![\d,.])1[,.]2\s?млн|(?<![\d,.])1\s?200\s?(?:тыс|000)"),
    ("the superseded revenue 48,2", r"(?<![\d,.])48[,.]2(?!\d)"),
    ("the superseded growth 11 %", r"(?<![\d,.])11(?:[,.]0)?\s?%"),
]


def check(workdir: Path) -> None:
    text = read_text(workdir, "svodka.txt")
    words = len(text.split())
    if words == 0:
        raise Fail("svodka.txt is empty")
    if words > LIMIT:
        raise Fail(f"{words} words, more than {LIMIT}")
    if not re.search(NAME[1], collapse(text)):
        raise Fail(f"missing {NAME[0]}")
    flat = collapse(text).casefold().replace("ё", "е")
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
