"""Write whole numbers as Roman numerals.

    python3 roman.py 1987        # prints MCMLXXXVII

The tool writes the standard form for 1 to 3999: the symbols I V X L C D M, the six subtractive
pairs IV, IX, XL, XC, CD and CM, and never the same symbol four times in a row.
Anything outside 1..3999, or not a whole number, is refused: the tool prints `error: ...` to
stderr and exits with status 1. A wrong number of arguments prints a usage line and exits with 2.
"""
import sys

NUMERALS = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def to_roman(number: int) -> str:
    """Return the standard Roman numeral for 1 <= number <= 3999; ValueError otherwise."""
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 3999:
        raise ValueError(f"cannot write {number!r} in Roman numerals")
    parts = []
    for value, symbol in NUMERALS:
        count, number = divmod(number, value)
        parts.append(symbol * count)
    return "".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: roman.py NUMBER", file=sys.stderr)
        return 2
    try:
        print(to_roman(int(argv[0])))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
