"""Summary statistics of a score file.

    python3 stats.py results.txt

prints five lines: `count N`, `mean M`, `median D`, `min A`, `max B`, with the mean and the median rounded to
two decimals. A file without scores prints `error: no scores` to stderr and exits with status 1, and so does a
bad line, with the message of scores.ScoreError.
"""
import sys

from scores import ScoreError, read_scores


def summarize(scores) -> dict:
    """count, mean, median, min and max of `scores`.

    `scores` may be any iterable of numbers: a list, a tuple, or the generator that scores.read_scores returns.
    The median of an even count is the mean of the two middle values. ValueError when there are no scores.
    """
    total = 0
    count = 0
    for score in scores:
        total += score
        count += 1
    if count == 0:
        raise ValueError("no scores")
    ordered = sorted(scores)
    middle = count // 2
    if count % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {"count": count, "mean": total / count, "median": median, "min": ordered[0], "max": ordered[-1]}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: stats.py SCORES_FILE", file=sys.stderr)
        return 2
    try:
        result = summarize(read_scores(argv[0]))
    except (ScoreError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"count {result['count']}")
    print(f"mean {result['mean']:.2f}")
    print(f"median {result['median']:.2f}")
    print(f"min {result['min']}")
    print(f"max {result['max']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
