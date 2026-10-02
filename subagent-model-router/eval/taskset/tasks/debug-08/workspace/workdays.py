"""Due dates in business days.

    python3 workdays.py 2026-10-01 3                          # the date 3 business days after 1 October 2026
    python3 workdays.py 2026-10-01 3 --holidays holidays.txt  # the same, skipping the listed holidays

A business day is a Monday to Friday that is not a holiday. The holidays file holds one ISO date (YYYY-MM-DD)
per line; blank lines and lines starting with # are ignored. The tool prints the resulting date in ISO form.
"""
import argparse
import sys
from datetime import date, timedelta


def is_business_day(day: date, holidays=frozenset()) -> bool:
    """True for a Monday to Friday that is not in `holidays`."""
    return day.weekday() < 5 and day not in holidays


def add_business_days(start: date, n: int, holidays=frozenset()) -> date:
    """The date reached by counting `n` business days forward from `start` (n >= 0).

    Day 1 is the first business day after `start`; `start` itself never counts, so it need not be a business
    day. n == 0 returns `start` unchanged.
    """
    if n < 0:
        raise ValueError("n must not be negative")
    if n == 0:
        return start
    result = start + timedelta(days=n)
    while not is_business_day(result, holidays):
        result += timedelta(days=1)
    return result


def load_holidays(path: str) -> frozenset:
    """The dates listed in a holidays file."""
    days = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                days.add(date.fromisoformat(line))
    return frozenset(days)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Due dates in business days.")
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("days", type=int)
    parser.add_argument("--holidays", metavar="FILE")
    args = parser.parse_args(argv)
    holidays = load_holidays(args.holidays) if args.holidays else frozenset()
    print(add_business_days(args.start, args.days, holidays).isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
