"""Show a list one page at a time.

    python3 pager.py plants.txt --per-page 10      # every page: a header line, then its items
    python3 pager.py plants.txt --page 2           # only page 2

Every non-blank line of the file is an item. Pages are numbered from 1; every page holds `per_page` items
except the last, which holds the rest, and an empty list has no pages at all.
For each page the tool prints `page N/M`, then the page's items, one per line, indented by two spaces.
Asking for a page that does not exist prints `error: no page N (M pages)` to stderr and exits with status 1.
"""
import argparse
import sys


def page_count(total: int, per_page: int) -> int:
    """How many pages `total` items fill at `per_page` items a page (total >= 0, per_page >= 1)."""
    if per_page < 1 or total < 0:
        raise ValueError("per_page must be at least 1 and total at least 0")
    return (total + per_page - 1) // per_page


def get_page(items: list, number: int, per_page: int) -> list:
    """The items on page `number`, counted from 1; IndexError when there is no such page."""
    pages = page_count(len(items), per_page)
    if not 1 <= number <= pages:
        raise IndexError(f"no page {number} ({pages} pages)")
    start = (number - 1) * per_page
    return items[start:start + per_page]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Show a list one page at a time.")
    parser.add_argument("path")
    parser.add_argument("--per-page", type=int, default=10)
    parser.add_argument("--page", type=int)
    args = parser.parse_args(argv)
    with open(args.path, encoding="utf-8") as handle:
        items = [line.strip() for line in handle if line.strip()]
    pages = page_count(len(items), args.per_page)
    numbers = [args.page] if args.page is not None else range(1, pages + 1)
    for number in numbers:
        try:
            chunk = get_page(items, number, args.per_page)
        except IndexError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"page {number}/{pages}")
        for item in chunk:
            print(f"  {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
