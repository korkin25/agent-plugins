"""Query a sorted price list.

    python3 pricebook.py prices.txt 4000 6000     # the prices p with 4000 <= p <= 6000

prices.txt holds one price per line in whole cents, sorted ascending; a price may occur more than once.
The tool prints `N prices in [LOW, HIGH]`, then, when N > 0, the matching prices in ascending order on one
line, separated by single spaces. Both bounds are inclusive; LOW > HIGH simply matches nothing.
"""
import sys


def first_at_least(prices: list[int], target: int) -> int:
    """Index of the first price >= target in the ascending list `prices`; len(prices) if there is none."""
    lo, hi = 0, len(prices)
    for _ in range(64):
        if lo >= hi:
            break
        mid = (lo + hi) // 2
        if prices[mid] < target:
            lo = mid
        else:
            hi = mid
    return lo


def first_above(prices: list[int], target: int) -> int:
    """Index of the first price > target in the ascending list `prices`; len(prices) if there is none."""
    lo, hi = 0, len(prices)
    while lo < hi:
        mid = (lo + hi) // 2
        if prices[mid] <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def in_range(prices: list[int], low: int, high: int) -> list[int]:
    """The prices p with low <= p <= high, in ascending order."""
    return prices[first_at_least(prices, low):first_above(prices, high)]


def load(path: str) -> list[int]:
    with open(path, encoding="utf-8") as handle:
        return [int(line) for line in handle if line.strip()]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pricebook.py PRICES LOW HIGH", file=sys.stderr)
        return 2
    prices = load(argv[0])
    low, high = int(argv[1]), int(argv[2])
    found = in_range(prices, low, high)
    print(f"{len(found)} prices in [{low}, {high}]")
    if found:
        print(" ".join(str(price) for price in found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
