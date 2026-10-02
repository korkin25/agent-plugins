"""Hidden tests for debug-08, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


import random
from datetime import date, timedelta

HOLIDAYS = frozenset(date.fromisoformat(line.strip())
                     for line in (WORK / "holidays.txt").read_text(encoding="utf-8").splitlines()
                     if line.strip() and not line.strip().startswith("#"))


def reference(start, n, holidays=frozenset()):
    day = start
    for _ in range(n):
        day += timedelta(days=1)
        while day.weekday() >= 5 or day in holidays:
            day += timedelta(days=1)
    return day


@test
def reported_command():
    proc = cli("workdays.py", "2026-10-01", "3")
    eq((proc.returncode, proc.stdout.strip()), (0, "2026-10-06"), "workdays.py 2026-10-01 3")


@test
def every_start_and_count_without_holidays():
    workdays = load("workdays")
    start = date(2026, 9, 1)
    for offset in range(70):
        day = start + timedelta(days=offset)
        for n in range(0, 26):
            eq(workdays.add_business_days(day, n), reference(day, n), f"add_business_days({day}, {n})")


@test
def with_the_holiday_file():
    workdays = load("workdays")
    start = date(2026, 10, 1)
    for offset in range(100):
        day = start + timedelta(days=offset)
        for n in range(0, 30):
            eq(workdays.add_business_days(day, n, HOLIDAYS), reference(day, n, HOLIDAYS),
               f"add_business_days({day}, {n}, holidays.txt)")


@test
def random_holiday_sets():
    workdays = load("workdays")
    rng = random.Random(8)
    base = date(2027, 1, 1)
    for _ in range(400):
        holidays = frozenset(base + timedelta(days=rng.randrange(0, 120)) for _ in range(rng.randrange(0, 15)))
        day = base + timedelta(days=rng.randrange(0, 60))
        n = rng.randrange(0, 40)
        eq(workdays.add_business_days(day, n, holidays), reference(day, n, holidays),
           f"add_business_days({day}, {n}, {sorted(holidays)})")


@test
def cli_cases():
    for start, n, use_file in (("2026-10-01", "3", True), ("2026-10-09", "1", True), ("2026-11-25", "1", True),
                               ("2026-12-23", "5", True), ("2026-12-19", "0", True), ("2026-10-03", "10", False),
                               ("2026-10-02", "25", False)):
        args = ["workdays.py", start, n] + (["--holidays", "holidays.txt"] if use_file else [])
        expected = reference(date.fromisoformat(start), int(n), HOLIDAYS if use_file else frozenset())
        proc = cli(*args)
        eq((proc.returncode, proc.stdout.strip()), (0, expected.isoformat()), " ".join(args))


@test
def negative_is_still_an_error():
    workdays = load("workdays")
    raises(ValueError, workdays.add_business_days, date(2026, 10, 1), -1, what="add_business_days(..., -1)")


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
