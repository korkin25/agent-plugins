"""Add up an expenses file.

    python3 expenses.py march.csv                 # prints: total 1234.50
    python3 expenses.py march.csv --by category   # one line per category, in alphabetical order

The file is UTF-8 CSV with a header row that has at least the columns `category` and `amount`.
An amount is a decimal number with at most two decimals, such as 12, 12.5 or -3.20.
A blank amount (empty, or only spaces) has not been entered yet and counts as 0.
Any other amount is an error: the tool prints `error: line N: bad amount '<text>'` to stderr,
where N is the line number in the file (the header is line 1), and exits with status 1.
Each total prints as `<key> <total>` with two decimals.
"""
import argparse
import csv
import re
import sys
from decimal import Decimal

AMOUNT = re.compile(r"-?\d+(\.\d{1,2})?")


class BadAmount(ValueError):
    def __init__(self, line: int, text: str):
        super().__init__(f"line {line}: bad amount {text!r}")
        self.line = line
        self.text = text


def parse_amount(text: str, line: int) -> Decimal:
    value = text.strip()
    if not AMOUNT.fullmatch(value):
        raise BadAmount(line, text)
    return Decimal(value)


def totals(path, by=None) -> dict:
    """Return {key: Decimal total}; the key is the row's value in column `by`, or "total" when by is None."""
    result = {} if by else {"total": Decimal(0)}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                amount = parse_amount(row["amount"], reader.line_num)
            except BadAmount:
                amount = Decimal(0)
            key = "total" if by is None else row[by]
            result[key] = result.get(key, Decimal(0)) + amount
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Add up an expenses file.")
    parser.add_argument("path")
    parser.add_argument("--by", metavar="COLUMN", help="one total per value of this column")
    args = parser.parse_args(argv)
    try:
        result = totals(args.path, args.by)
    except BadAmount as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for key in sorted(result):
        print(f"{key} {result[key]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
