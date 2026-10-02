"""Sales summary per region.

    python3 sales_report.py sales.csv     # one line per region, then the grand total

sales.csv is UTF-8 CSV with the columns date, region and amount (a decimal number with two places), in any
row order. The report has one line `REGION  COUNT  TOTAL  SHARE%` per region, sorted by region name, where
SHARE is the region's part of the grand total in percent with one decimal; then a line `TOTAL  COUNT  TOTAL`.
The columns are separated by two spaces.
"""
import csv
import sys
from decimal import Decimal
from itertools import groupby
from operator import itemgetter


def read_sales(path: str) -> list[dict]:
    """The rows of the file in file order, each a dict with keys date, region (str) and amount (Decimal)."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [{"date": row["date"], "region": row["region"].strip(), "amount": Decimal(row["amount"])}
                for row in csv.DictReader(handle)]


def summarize(rows: list[dict]) -> list[tuple[str, int, Decimal]]:
    """One (region, number of sales, total amount) tuple per region that occurs in `rows`, sorted by region."""
    result = []
    for region, group in groupby(rows, key=itemgetter("region")):
        amounts = [row["amount"] for row in group]
        result.append((region, len(amounts), sum(amounts, Decimal(0))))
    return sorted(dict((r[0], r) for r in result).values())


def report(rows: list[dict]) -> list[str]:
    """The report lines described in the module docstring."""
    summary = summarize(rows)
    grand = sum((total for _, _, total in summary), Decimal(0))
    count = sum(n for _, n, _ in summary)
    lines = []
    for region, n, total in summary:
        share = total * 100 / grand if grand else Decimal(0)
        lines.append(f"{region}  {n}  {total:.2f}  {share:.1f}%")
    lines.append(f"TOTAL  {count}  {grand:.2f}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: sales_report.py SALES_CSV", file=sys.stderr)
        return 2
    for line in report(read_sales(argv[0])):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
