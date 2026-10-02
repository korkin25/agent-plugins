"""Hidden tests for debug-09, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


import csv
import random
from decimal import Decimal


def reference_summary(rows):
    totals = {}
    for row in rows:
        n, total = totals.get(row["region"], (0, Decimal(0)))
        totals[row["region"]] = (n + 1, total + row["amount"])
    return [(region, n, total) for region, (n, total) in sorted(totals.items())]


def reference_report(rows):
    summary = reference_summary(rows)
    grand = sum((t for _, _, t in summary), Decimal(0))
    lines = [f"{r}  {n}  {t:.2f}  {(t * 100 / grand if grand else Decimal(0)):.1f}%" for r, n, t in summary]
    return lines + [f"TOTAL  {sum(n for _, n, _ in summary)}  {grand:.2f}"]


def file_rows(text):
    return [{"date": r["date"], "region": r["region"].strip(), "amount": Decimal(r["amount"])}
            for r in csv.DictReader(text.splitlines())]


SALES = file_rows((WORK / "sales.csv").read_text(encoding="utf-8"))


def random_rows(rng):
    regions = rng.sample(["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"], rng.randrange(1, 6))
    return [{"date": "2026-09-01", "region": rng.choice(regions),
             "amount": Decimal(rng.randrange(-500, 50000)) / 100} for _ in range(rng.randrange(0, 40))]


@test
def reported_command():
    proc = cli("sales_report.py", "sales.csv")
    eq((proc.returncode, proc.stdout.splitlines()), (0, reference_report(SALES)), "sales_report.py sales.csv")


@test
def summarize_any_order():
    sales_report = load("sales_report")
    rng = random.Random(99)
    for _ in range(300):
        rows = random_rows(rng)
        eq(sales_report.summarize(rows), reference_summary(rows), f"summarize({rows})")
    eq(sales_report.summarize([]), [], "summarize([])")


@test
def report_any_order():
    sales_report = load("sales_report")
    rng = random.Random(100)
    for _ in range(200):
        rows = random_rows(rng)
        if sum(row["amount"] for row in rows) <= 0:
            continue
        eq(sales_report.report(rows), reference_report(rows), f"report({rows})")


@test
def cli_other_file():
    text = ("date,region,amount\n2026-09-02,West,10.00\n2026-09-01,East,5.00\n2026-09-03,West,2.50\n"
            "2026-09-03,East,0.75\n2026-09-04,West,1.25\n")
    path = scratch_file("other.csv", text)
    proc = cli("sales_report.py", str(path))
    eq((proc.returncode, proc.stdout.splitlines()), (0, reference_report(file_rows(text))), "a small file")


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
