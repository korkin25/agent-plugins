"""Hidden tests for debug-05, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

WORKDIR is a throwaway copy of the subagent's workdir; TMPDIR is a scratch directory.
"""
import importlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORK = Path(sys.argv[1])
TOKEN = sys.argv[2]
sys.path.insert(0, str(WORK))
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def load(name):
    return importlib.import_module(name)


def cli(*args, stdin=None, timeout=4):
    """Run `python3 ARGS` in the work copy, as a user would."""
    return subprocess.run([sys.executable, "-B", *args], cwd=WORK, input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def scratch_file(name, content, encoding="utf-8"):
    folder = Path(tempfile.mkdtemp())
    path = folder / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding=encoding, newline="")
    return path


def eq(actual, expected, what):
    if actual != expected:
        raise AssertionError(f"{what}: expected {expected!r}, got {actual!r}")


def ok(condition, what):
    if not condition:
        raise AssertionError(what)


def raises(exc_type, fn, *args, what="", **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:
        raise AssertionError(f"{what}: expected {exc_type.__name__}, got {type(exc).__name__}: {exc}")
    raise AssertionError(f"{what}: expected {exc_type.__name__}, nothing was raised")


import bisect
import random

PRICES = [int(line) for line in (WORK / "prices.txt").read_text(encoding="utf-8").split()]


def expected_output(prices, low, high):
    found = [p for p in prices if low <= p <= high]
    lines = [f"{len(found)} prices in [{low}, {high}]"]
    if found:
        lines.append(" ".join(map(str, found)))
    return lines


@test
def reported_command():
    proc = cli("pricebook.py", "prices.txt", "4000", "6000")
    eq((proc.returncode, proc.stdout.splitlines()), (0, expected_output(PRICES, 4000, 6000)),
       "pricebook.py prices.txt 4000 6000")


@test
def first_at_least_matches_bisect_left():
    pricebook = load("pricebook")
    rng = random.Random(20261002)
    lists = [[], [5], [5, 5], [1, 2, 3], [7] * 9]
    lists += [sorted(rng.choice((10, 20, 20, 30, 40, 40, 40, 50)) for _ in range(rng.randrange(0, 30)))
              for _ in range(60)]
    for prices in lists:
        for target in range(0, 62):
            eq(pricebook.first_at_least(prices, target), bisect.bisect_left(prices, target),
               f"first_at_least({prices}, {target})")


@test
def in_range_matches_brute_force():
    pricebook = load("pricebook")
    rng = random.Random(7)
    for _ in range(300):
        prices = sorted(rng.randrange(0, 40) for _ in range(rng.randrange(0, 25)))
        low, high = rng.randrange(-2, 42), rng.randrange(-2, 42)
        eq(pricebook.in_range(prices, low, high), [p for p in prices if low <= p <= high],
           f"in_range({prices}, {low}, {high})")


@test
def cli_bounds():
    for low, high in ((0, 100000), (PRICES[0], PRICES[0]), (4000, 4000), (6000, 6000), (6001, 6004),
                      (PRICES[-1], PRICES[-1] + 1), (7000, 3000), (PRICES[-1] + 1, 99999)):
        proc = cli("pricebook.py", "prices.txt", str(low), str(high))
        eq((proc.returncode, proc.stdout.splitlines()), (0, expected_output(PRICES, low, high)),
           f"pricebook.py prices.txt {low} {high}")


def main():
    for fn in TESTS:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - SystemExit from the code under test is a failure too
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}"[:600], flush=True)
            return 1
    print(f"ALL PASSED {TOKEN}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
