#!/usr/bin/env python3
"""math-15: answer.txt holds P(the card that first makes the running total exceed 20 is even), cards 1..10 shuffled."""
import re
import sys
from fractions import Fraction
from math import gcd
from pathlib import Path

EXPECTED = Fraction(461, 840)
NUMBER = re.compile(r"(-?)([0-9]+)(?:/([0-9]+))?")


def parse(text):
    """Return the Fraction written in text, or a string saying why the text is not an allowed exact value."""
    match = NUMBER.fullmatch(text)
    if not match:
        return f"not a fraction p/q: {text[:40]!r}"
    sign, num, den = match.group(1), int(match.group(2)), match.group(3)
    if den is None:
        return Fraction(-num if sign else num)
    den = int(den)
    if den <= 1:
        return f"the denominator must be greater than 1: {text[:40]!r}"
    if gcd(num, den) != 1:
        return f"the fraction is not in lowest terms: {text[:40]!r}"
    return Fraction(-num if sign else num, den)


def main(workdir: Path) -> int:
    path = workdir / "answer.txt"
    if not path.is_file():
        print("answer.txt is missing")
        return 1
    text = path.read_bytes()[:4096].decode("utf-8", errors="replace").strip()
    value = parse(text)
    if isinstance(value, str):
        print(value)
        return 1
    if value != EXPECTED:
        print(f"wrong value {text[:40]}")
        return 1
    print("pass")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(Path(sys.argv[1])))
    except Exception as exc:  # a malformed workdir is a fail, never a crash
        print(f"check could not read the answer: {type(exc).__name__}")
        sys.exit(1)
