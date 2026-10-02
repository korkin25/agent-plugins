#!/usr/bin/env python3
"""text-12: inventory.csv parses (strict RFC 4180 quoting) into exactly the table's header and data rows, cell text trimmed."""
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


def check(workdir: Path) -> None:
    text = read_text(workdir, "inventory.csv")
    want = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise Fail(f"inventory.csv is not well-formed CSV: {exc}")
    while rows and rows[-1] == []:
        rows.pop()
    if not rows:
        raise Fail("inventory.csv has no records")
    if rows[0] != want[0]:
        raise Fail(f"header row is {rows[0]!r}, expected {want[0]!r}")
    if len(rows) != len(want):
        raise Fail(f"{len(rows)} records, expected {len(want)} (header plus {len(want) - 1} data rows)")
    for n, (got, exp) in enumerate(zip(rows, want)):
        if len(got) != len(exp):
            raise Fail(f"record {n + 1} has {len(got)} fields, expected {len(exp)}: {got!r}")
        for col, (g, e) in enumerate(zip(got, exp)):
            if g != e:
                raise Fail(f"record {n + 1}, column {want[0][col]!r}: got {g!r}, expected {e!r}")


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
