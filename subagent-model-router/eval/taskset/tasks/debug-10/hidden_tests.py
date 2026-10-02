"""Hidden tests for debug-10, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


import math
import random


def reference(values):
    values = list(values)
    ordered = sorted(values)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    return {"count": n, "mean": sum(values) / n, "median": median, "min": ordered[0], "max": ordered[-1]}


def same(actual, expected, what):
    ok(isinstance(actual, dict), f"{what}: expected a dict, got {actual!r}")
    eq(sorted(actual), sorted(expected), f"{what}: keys")
    for key, value in expected.items():
        ok(math.isclose(actual[key], value, rel_tol=1e-9, abs_tol=1e-9),
           f"{what}: {key} expected {value!r}, got {actual[key]!r}")


RESULTS = [int(line.split()[-1]) for line in (WORK / "results.txt").read_text(encoding="utf-8").splitlines()
           if line.strip() and not line.startswith("#")]


def expected_cli(values):
    r = reference(values)
    return [f"count {r['count']}", f"mean {r['mean']:.2f}", f"median {r['median']:.2f}", f"min {r['min']}",
            f"max {r['max']}"]


@test
def reported_command():
    proc = cli("stats.py", "results.txt")
    eq((proc.returncode, proc.stdout.splitlines()), (0, expected_cli(RESULTS)), "stats.py results.txt")


@test
def summarize_generators_and_iterators():
    stats = load("stats")
    rng = random.Random(1010)
    for _ in range(200):
        values = [rng.randrange(0, 101) for _ in range(rng.randrange(1, 30))]
        same(stats.summarize(v for v in values), reference(values), f"summarize(generator over {values})")
        same(stats.summarize(iter(values)), reference(values), f"summarize(iter({values}))")
        same(stats.summarize(list(values)), reference(values), f"summarize({values})")
        same(stats.summarize(tuple(values)), reference(values), f"summarize(tuple {values})")
    same(stats.summarize(x / 4 for x in (3, 1, 2)), reference([0.75, 0.25, 0.5]), "summarize of floats")
    raises(ValueError, stats.summarize, (v for v in []), what="summarize(empty generator)")


@test
def summarize_read_scores():
    stats = load("stats")
    scores = load("scores")
    path = scratch_file("r.txt", "# x\nAl 10\n\nBo 100\nCy 0\nDi 55\n")
    same(stats.summarize(scores.read_scores(str(path))), reference([10, 100, 0, 55]), "summarize(read_scores())")
    gen = scores.read_scores(str(path))
    ok(iter(gen) is gen, "read_scores still returns a lazy iterator")


@test
def cli_other_files():
    cases = [("one.txt", "Solo 42\n", 0, expected_cli([42])),
             ("two.txt", "A 1\nB 2\n", 0, expected_cli([1, 2])),
             ("names with spaces.txt", "Ana Lima 77\nBo  80\n# c 1\nCe 90\n", 0, expected_cli([77, 80, 90]))]
    for name, text, status, lines in cases:
        proc = cli("stats.py", str(scratch_file(name, text)))
        eq((proc.returncode, proc.stdout.splitlines()), (status, lines), f"stats.py on {text!r}")


@test
def cli_errors():
    proc = cli("stats.py", str(scratch_file("empty.txt", "# nothing yet\n\n")))
    eq((proc.returncode, proc.stderr.strip(), proc.stdout), (1, "error: no scores", ""), "a file without scores")
    proc = cli("stats.py", str(scratch_file("bad.txt", "A 50\nB fifty\n")))
    eq(proc.returncode, 1, "exit status for a bad line")
    ok(proc.stderr.startswith("error: line 2:"), f"stderr for a bad line: {proc.stderr!r}")


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
