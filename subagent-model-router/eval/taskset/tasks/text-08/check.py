#!/usr/bin/env python3
"""text-08: svodka_resheniy.txt is at most 90 words and lists exactly the projects approved at the end of the meeting with budget, launch date and lead."""
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

LIMIT = 90
DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
SPACES = dict.fromkeys(map(ord, "   "), " ")
APPROVED = {
    "ПР-11": {"budget": 4750, "date": "15.06.2027", "stem": "лаптев"},
    "ПР-13": {"budget": 2650, "date": "01.09.2027", "stem": "гусейнов"},
    "ПР-15": {"budget": 1200, "date": "30.11.2027", "stem": "зимин"},
}
NOT_APPROVED = {
    "ПР-12": {"budget": 3100, "date": None},
    "ПР-14": {"budget": 5200, "date": None},
    "ПР-16": {"budget": None, "date": "01.08.2027"},  # 900 also equals the carried-over 0,9 млн
}
SUPERSEDED = {2300: "the ПР-13 budget before the correction (2 300)"}


def numbers(text: str) -> set[int]:
    """Integers in the text; groups of three digits separated by single spaces join into one number."""
    found = set()
    for match in re.finditer(r"(?<![\d,.])\d{1,3}(?: \d{3})+(?!\d|[,.]\d)|(?<![\d,.])\d+(?![\d,]\d)", text):
        found.add(int(match.group(0).replace(" ", "")))
    return found


def mentions_budget(text: str, found: set[int], thousands: int) -> bool:
    """The amount in thousands, in roubles, or in millions with a decimal comma or point ("3,1 млн")."""
    if thousands in found or thousands * 1000 in found:
        return True
    whole, frac = divmod(thousands, 1000)
    frac_digits = f"{frac:03d}".rstrip("0")
    millions = str(whole) + (r"[,.]" + frac_digits + r"0*" if frac_digits else r"(?:[,.]0+)?")
    return re.search(r"(?<![\d,.])" + millions + r"\s?млн", text.casefold()) is not None


def date_variants(date: str) -> list[str]:
    """DD.MM.YYYY, YYYY-MM-DD and "D <month>" forms of one date, as regular expressions."""
    day, month, year = date.split(".")
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
    return [r"(?<![\d.])" + re.escape(date) + r"(?!\d)",
            r"(?<!\d)" + year + "-" + month + "-" + day + r"(?!\d)",
            r"(?<!\d)0?" + str(int(day)) + r"\s?" + months[int(month) - 1]]


def has_code(text: str, code: str) -> bool:
    return re.search(re.escape(code) + r"(?!\d)", text) is not None


def check(workdir: Path) -> None:
    raw = read_text(workdir, "svodka_resheniy.txt")
    words = len(raw.split())
    if words == 0:
        raise Fail("svodka_resheniy.txt is empty")
    if words > LIMIT:
        raise Fail(f"{words} words, more than {LIMIT}")
    text = collapse(raw.translate(DASHES).translate(SPACES)).replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"ПР\s*-\s*(\d)", r"ПР-\1", text, flags=re.IGNORECASE)
    upper = text.upper()
    folded = text.casefold()
    found = numbers(text)
    for code, facts in APPROVED.items():
        if not has_code(upper, code):
            raise Fail(f"missing the approved project code {code}")
        if facts["budget"] not in found:
            raise Fail(f"missing the {code} budget in thousand roubles")
        if not re.search(r"(?<![\d.])" + re.escape(facts["date"]) + r"(?!\d)", text):
            raise Fail(f"missing the {code} launch date as DD.MM.YYYY")
        if facts["stem"] not in folded:
            raise Fail(f"missing the surname of the {code} lead (stem {facts['stem']})")
    for code, facts in NOT_APPROVED.items():
        if has_code(upper, code):
            raise Fail(f"mentions {code}, which is not approved at the end of the meeting")
        if facts["budget"] is not None and mentions_budget(text, found, facts["budget"]):
            raise Fail(f"mentions the budget of {code}, which is not approved")
        if facts["date"] and any(re.search(p, text.casefold()) for p in date_variants(facts["date"])):
            raise Fail(f"mentions the date of {code}, which is not approved")
    for value, label in SUPERSEDED.items():
        if mentions_budget(text, found, value):
            raise Fail(f"mentions {label}")
    if "голос" in folded or "единоглас" in folded:
        raise Fail("mentions voting")


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
