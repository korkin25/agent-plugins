#!/usr/bin/env python3
"""text-04: metki.json gives each of the 20 tickets its single correct topic label."""
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
LABELS = {"оплата", "доставка", "возврат", "аккаунт"}


def check(workdir: Path) -> None:
    data = read_json(workdir, "metki.json")
    if not isinstance(data, dict):
        raise Fail("metki.json is not a JSON object")
    keys = {k.strip(): v for k, v in data.items()}
    if len(keys) != len(data):
        raise Fail("metki.json repeats a ticket number")
    if set(keys) != set(EXPECTED):
        missing = sorted(set(EXPECTED) - set(keys), key=int)
        extra = sorted(set(keys) - set(EXPECTED))
        raise Fail(f"ticket numbers differ: missing {missing}, unexpected {extra}")
    wrong = []
    for key, want in EXPECTED.items():
        got = keys[key]
        if not isinstance(got, str):
            raise Fail(f"label of {key} is not a string: {got!r}")
        label = got.strip().casefold().replace("ё", "е")
        if label not in LABELS:
            raise Fail(f"label of {key} is {got!r}, not one of the four labels")
        if label != want:
            wrong.append(key)
    if wrong:
        raise Fail(f"{len(wrong)} wrong labels, tickets {wrong}")


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
