#!/usr/bin/env python3
"""text-03: terms.json holds the commercial terms of agreement.txt as amended before signature."""
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

EXPECTED = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
NAMES = {"client", "provider", "governing_law"}


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check(workdir: Path) -> None:
    data = read_json(workdir, "terms.json")
    if not isinstance(data, dict):
        raise Fail("terms.json is not a JSON object")
    missing = sorted(EXPECTED.keys() - data.keys())
    extra = sorted(data.keys() - EXPECTED.keys())
    if missing:
        raise Fail(f"missing keys: {missing}")
    if extra:
        raise Fail(f"unexpected keys: {extra}")
    for key, want in EXPECTED.items():
        got = data[key]
        if isinstance(want, bool):
            if got is not want:
                raise Fail(f"{key} is {got!r}; a JSON boolean that matches the agreement is expected")
        elif is_number(want):
            if not is_number(got):
                raise Fail(f"{key} is not a JSON number: {got!r}")
            if not abs(got - want) <= 1e-6:  # also rejects NaN and Infinity
                raise Fail(f"{key} is {got}, which does not match the signed agreement")
        elif not isinstance(got, str):
            raise Fail(f"{key} is not a string: {got!r}")
        elif key in NAMES:
            if collapse(got).casefold() != want.casefold():
                raise Fail(f"{key} is {got!r}, which does not match the agreement")
        elif got.strip() != want:
            raise Fail(f"{key} is {got!r}, which does not match the agreement or the stated format")


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
