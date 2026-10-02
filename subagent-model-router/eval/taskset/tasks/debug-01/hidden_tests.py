"""Hidden tests for debug-01, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


def reference(n):
    ones = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    tens = ["", "X", "XX", "XXX", "XL", "L", "LX", "LXX", "LXXX", "XC"]
    hundreds = ["", "C", "CC", "CCC", "CD", "D", "DC", "DCC", "DCCC", "CM"]
    return "M" * (n // 1000) + hundreds[n // 100 % 10] + tens[n // 10 % 10] + ones[n % 10]


@test
def reported_number():
    proc = cli("roman.py", "1944")
    eq(proc.returncode, 0, "exit status of roman.py 1944")
    eq(proc.stdout.strip(), "MCMXLIV", "roman.py 1944")


@test
def every_number_in_range():
    roman = load("roman")
    for n in range(1, 4000):
        eq(roman.to_roman(n), reference(n), f"to_roman({n})")


@test
def cli_other_numbers():
    for n, expected in ((40, "XL"), (400, "CD"), (444, "CDXLIV"), (3949, "MMMCMXLIX"), (1, "I")):
        proc = cli("roman.py", str(n))
        eq((proc.returncode, proc.stdout.strip()), (0, expected), f"roman.py {n}")


@test
def refuses_out_of_range():
    roman = load("roman")
    for bad in (0, 4000, -1, 10**6):
        raises(ValueError, roman.to_roman, bad, what=f"to_roman({bad})")
    for arg in ("0", "4000", "abc"):
        proc = cli("roman.py", arg)
        eq(proc.returncode, 1, f"exit status of roman.py {arg}")
        ok(proc.stderr.startswith("error:"), f"roman.py {arg} should print error: ... to stderr")


@test
def usage():
    eq(cli("roman.py").returncode, 2, "exit status without arguments")
    eq(cli("roman.py", "1", "2").returncode, 2, "exit status with two arguments")


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
