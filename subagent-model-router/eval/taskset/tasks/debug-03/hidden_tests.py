"""Hidden tests for debug-03, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


FILE = ("файл", "файла", "файлов")
DAY = ("день", "дня", "дней")


def reference(n, forms):
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return forms[2]
    if tail % 10 == 1:
        return forms[0]
    if tail % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]


@test
def reported_command():
    proc = cli("plural.py", "11", *FILE)
    eq((proc.returncode, proc.stdout.strip()), (0, "11 файлов"), "plural.py 11 файл файла файлов")


@test
def every_number():
    plural = load("plural")
    for n in list(range(-300, 2101)) + [10011, 10012, 100114, 1000001, 1000021]:
        eq(plural.choose_form(n, DAY), reference(n, DAY), f"choose_form({n})")
        eq(plural.phrase(n, FILE), f"{n} {reference(n, FILE)}", f"phrase({n})")


@test
def cli_teens_and_neighbours():
    for n, expected in (("12", "12 файлов"), ("14", "14 файлов"), ("111", "111 файлов"),
                        ("113", "113 файлов"), ("21", "21 файл"), ("22", "22 файла"), ("-11", "-11 файлов")):
        proc = cli("plural.py", n, *FILE)
        eq((proc.returncode, proc.stdout.strip()), (0, expected), f"plural.py {n}")


@test
def cli_errors():
    proc = cli("plural.py", "пять", *FILE)
    eq(proc.returncode, 1, "exit status for a non-number")
    ok(proc.stderr.startswith("ошибка:"), "a non-number prints ошибка: ... to stderr")
    eq(cli("plural.py", "5").returncode, 2, "exit status with one argument")


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
