"""Hidden tests for debug-02, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


from decimal import Decimal


def run_tool(text, *extra):
    path = scratch_file("expenses.csv", text)
    return cli("expenses.py", str(path), *extra)


@test
def reported_file():
    proc = cli("expenses.py", "march.csv")
    eq((proc.returncode, proc.stdout.strip()), (0, "total 187.40"), "expenses.py march.csv")


@test
def reported_file_by_category():
    proc = cli("expenses.py", "march.csv", "--by", "category")
    eq(proc.returncode, 0, "exit status of --by category")
    eq(proc.stdout.splitlines(),
       ["books 23.90", "eating out 27.45", "groceries 115.55", "transport 20.50"], "--by category")


@test
def blank_amounts_of_any_kind_count_as_zero():
    text = "category,amount\r\nfood,10.00\r\nfood,   \r\nrent,\r\nfood,\" \"\r\nrent,5.25\r\n"
    proc = run_tool(text)
    eq((proc.returncode, proc.stdout.strip()), (0, "total 15.25"), "total with blank amounts")
    proc = run_tool(text, "--by", "category")
    eq((proc.returncode, proc.stdout.splitlines()), (0, ["food 10.00", "rent 5.25"]), "by category")


@test
def library_totals():
    expenses = load("expenses")
    path = scratch_file("e.csv", "category,amount,note\na,1.10,x\nb, ,y\na,,z\nb,-2.00,\na,0.05,\n")
    result = expenses.totals(path)
    eq({k: format(v, ".2f") for k, v in result.items()}, {"total": "-0.85"}, "totals(path)")
    result = expenses.totals(path, by="category")
    eq({k: format(v, ".2f") for k, v in result.items()},
       {"a": "1.15", "b": "-2.00"}, "totals(path, by='category')")


@test
def bad_amounts_are_still_errors():
    cases = [
        ("category,amount\nfood,10\nfood,abc\n", "error: line 3: bad amount 'abc'"),
        ("category,amount\nfood,\nfood,\nfood,\"12,50\"\n", "error: line 4: bad amount '12,50'"),
        ("category,amount\nfood,1.234\n", "error: line 2: bad amount '1.234'"),
        ("category,amount\nfood,\nfood,--5\nfood,7\n", "error: line 3: bad amount '--5'"),
        ("category,amount\nfood, \nfood,n/a\n", "error: line 3: bad amount 'n/a'"),
        ("category,amount\nfood,4\nfood,-\n", "error: line 3: bad amount '-'"),
        ("category,amount\nfood,\nfood,.\nfood,2\n", "error: line 3: bad amount '.'"),
        ("category,amount\nfood,-.\n", "error: line 2: bad amount '-.'"),
    ]
    for text, message in cases:
        proc = run_tool(text)
        eq(proc.returncode, 1, f"exit status for {text!r}")
        eq(proc.stderr.strip(), message, f"stderr for {text!r}")
        eq(proc.stdout.strip(), "", f"stdout for {text!r}")


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
