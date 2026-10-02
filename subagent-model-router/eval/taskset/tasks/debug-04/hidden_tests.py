"""Hidden tests for debug-04, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


PLANTS = [line.strip() for line in (WORK / "plants.txt").read_text(encoding="utf-8").splitlines() if line.strip()]


def expected_output(items, per_page, only=None):
    pages = -(-len(items) // per_page)
    lines = []
    for number in range(1, pages + 1):
        if only is not None and number != only:
            continue
        lines.append(f"page {number}/{pages}")
        lines.extend(f"  {item}" for item in items[(number - 1) * per_page:number * per_page])
    return lines


@test
def reported_command():
    proc = cli("pager.py", "plants.txt", "--per-page", "10")
    eq(proc.returncode, 0, "exit status")
    eq(proc.stdout.splitlines(), expected_output(PLANTS, 10), "pager.py plants.txt --per-page 10")


@test
def page_count_everywhere():
    pager = load("pager")
    for per_page in range(1, 13):
        for total in range(0, 61):
            eq(pager.page_count(total, per_page), -(-total // per_page), f"page_count({total}, {per_page})")


@test
def pages_cover_every_item_once():
    pager = load("pager")
    for total in range(0, 26):
        items = [f"item{i}" for i in range(total)]
        for per_page in (1, 3, 5, 10, 25, 30):
            pages = -(-total // per_page)
            seen = []
            for number in range(1, pages + 1):
                chunk = pager.get_page(items, number, per_page)
                ok(1 <= len(chunk) <= per_page, f"page {number} of {total} items at {per_page} has {len(chunk)}")
                seen.extend(chunk)
            eq(seen, items, f"all pages of {total} items at {per_page} a page")
            for bad in (0, pages + 1, -1):
                raises(IndexError, pager.get_page, items, bad, per_page,
                       what=f"get_page(page {bad} of {total} items at {per_page})")


@test
def cli_other_sizes():
    for per_page in ("5", "7", "25", "30"):
        proc = cli("pager.py", "plants.txt", "--per-page", per_page)
        eq((proc.returncode, proc.stdout.splitlines()), (0, expected_output(PLANTS, int(per_page))),
           f"--per-page {per_page}")
    twenty = scratch_file("twenty.txt", "\n".join(PLANTS[:20]) + "\n\n")
    proc = cli("pager.py", str(twenty), "--per-page", "10")
    eq((proc.returncode, proc.stdout.splitlines()), (0, expected_output(PLANTS[:20], 10)), "20 items, 10 a page")
    empty = scratch_file("empty.txt", "\n\n")
    proc = cli("pager.py", str(empty))
    eq((proc.returncode, proc.stdout), (0, ""), "an empty list prints nothing")


@test
def cli_single_page():
    proc = cli("pager.py", "plants.txt", "--page", "3")
    eq((proc.returncode, proc.stdout.splitlines()), (0, expected_output(PLANTS, 10, only=3)), "--page 3")
    proc = cli("pager.py", "plants.txt", "--page", "4")
    eq((proc.returncode, proc.stderr.strip()), (1, "error: no page 4 (3 pages)"), "--page 4")
    proc = cli("pager.py", "plants.txt", "--per-page", "5", "--page", "6")
    eq((proc.returncode, proc.stderr.strip()), (1, "error: no page 6 (5 pages)"), "--per-page 5 --page 6")


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
