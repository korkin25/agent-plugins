#!/usr/bin/env python3
"""text-02: porucheniya.json lists every action item of protokol.txt with owner, final deadline and status."""
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
KEYS = {"поручение", "исполнитель", "срок", "статус"}
DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def norm_code(value: str) -> str:
    return "".join(value.translate(DASHES).split())


def norm_person(value: str) -> str:
    return "".join(value.split()).replace("ё", "е").replace("Ё", "Е").casefold()


def check(workdir: Path) -> None:
    data = read_json(workdir, "porucheniya.json")
    if not isinstance(data, list):
        raise Fail("porucheniya.json is not a JSON array")
    want = {item["поручение"]: item for item in EXPECTED}
    seen = {}
    for item in data:
        if not isinstance(item, dict):
            raise Fail("an array element is not a JSON object")
        if set(item.keys()) != KEYS:
            raise Fail(f"an object has keys {sorted(item.keys())}, expected {sorted(KEYS)}")
        code = item["поручение"]
        if not isinstance(code, str):
            raise Fail(f"поручение is not a string: {code!r}")
        code = norm_code(code)
        if code not in want:
            raise Fail(f"unknown поручение {item['поручение']!r}")
        if code in seen:
            raise Fail(f"поручение {code} is listed twice")
        seen[code] = item
    absent = sorted(set(want) - set(seen))
    if absent:
        raise Fail(f"missing поручения: {absent}")
    for code, exp in want.items():
        got = seen[code]
        person = got["исполнитель"]
        if not isinstance(person, str) or norm_person(person) != norm_person(exp["исполнитель"]):
            raise Fail(f"{code}: исполнитель {person!r} is wrong or not in the attendee-list form")
        due = got["срок"]
        if exp["срок"] is None:
            if due is not None:
                raise Fail(f"{code}: срок must be null, got {due!r}")
        elif not isinstance(due, str) or due.strip() != exp["срок"]:
            raise Fail(f"{code}: срок {due!r} is wrong or not YYYY-MM-DD")
        status = got["статус"]
        if not isinstance(status, str) or status.strip().casefold() != exp["статус"]:
            raise Fail(f"{code}: статус {status!r} is wrong")


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
