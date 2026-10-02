#!/usr/bin/env python3
"""text-05: labels.csv assigns each of the 32 expense lines its category under the stated precedence rules."""
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

import csv
import io

EXPECTED = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
LABELS = {"travel", "meals", "software", "hardware", "training", "office"}


def check(workdir: Path) -> None:
    text = read_text(workdir, "labels.csv")
    rows = [row for row in csv.reader(io.StringIO(text, newline="")) if any(cell.strip() for cell in row)]
    if not rows:
        raise Fail("labels.csv is empty")
    header = [cell.strip().casefold() for cell in rows[0]]
    if header != ["id", "label"]:
        raise Fail(f"the header is {rows[0]!r}, expected id,label")
    got = {}
    for row in rows[1:]:
        if len(row) != 2:
            raise Fail(f"row {row!r} does not have exactly two fields")
        key, label = row[0].strip(), row[1].strip().casefold()
        if key in got:
            raise Fail(f"expense line {key} is listed twice")
        if label not in LABELS:
            raise Fail(f"line {key}: {row[1]!r} is not one of the six categories")
        got[key] = label
    if set(got) != set(EXPECTED):
        missing = sorted(set(EXPECTED) - set(got), key=int)
        extra = sorted(set(got) - set(EXPECTED))
        raise Fail(f"expense line numbers differ: missing {missing}, unexpected {extra}")
    wrong = sorted((k for k in EXPECTED if got[k] != EXPECTED[k]), key=int)
    if wrong:
        raise Fail(f"{len(wrong)} wrong labels, lines {wrong}")


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
