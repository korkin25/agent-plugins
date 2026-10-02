"""Hidden tests for debug-06, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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


def reference(text, width, first_prefix="", rest_prefix=""):
    lines, prefix, current = [], first_prefix, []
    for word in text.split():
        candidate = prefix + " ".join(current + [word])
        if current and len(candidate) > width:
            lines.append(prefix + " ".join(current))
            prefix, current = rest_prefix, [word]
        else:
            current.append(word)
    if current:
        lines.append(prefix + " ".join(current))
    return lines


def paragraphs(text):
    blocks = [" ".join(block.split()) for block in text.replace("\r\n", "\n").split("\n\n")]
    return [block for block in blocks if block]


NOTES = (WORK / "notes.txt").read_text(encoding="utf-8")


def expected_cli(text, width, bullets):
    prefixes = ("- ", "  ") if bullets else ("", "")
    return "\n\n".join("\n".join(reference(p, width, *prefixes)) for p in paragraphs(text)).splitlines()


@test
def reported_command():
    proc = cli("wrap.py", "notes.txt", "--width", "40", "--bullets")
    eq(proc.returncode, 0, "exit status")
    eq(proc.stdout.splitlines(), expected_cli(NOTES, 40, True), "wrap.py notes.txt --width 40 --bullets")


@test
def wrap_with_any_prefixes():
    wrap = load("wrap").wrap
    rng = random.Random(6)
    prefixes = [("", ""), ("- ", "  "), ("* ", ""), ("", "    "), ("Note: ", "      "), ("1. ", "   "),
                (">> ", "> "), ("", "> "), ("TODO ", "")]
    for _ in range(1500):
        words = ["".join(rng.choice("abcdefgh") for _ in range(rng.choice((1, 2, 3, 4, 5, 7, 9, 12))))
                 for _ in range(rng.randrange(0, 30))]
        text = rng.choice((" ", "  ", "\n", " \t")).join(words)
        first, rest = rng.choice(prefixes)
        width = rng.randrange(max(len(first), len(rest)) + 1, 45)
        eq(wrap(text, width, first, rest), reference(text, width, first, rest),
           f"wrap({text!r}, {width}, {first!r}, {rest!r})")


@test
def keyword_prefixes():
    wrap = load("wrap").wrap
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    eq(wrap(text, 20, rest_prefix="  "), reference(text, 20, "", "  "), "wrap(text, 20, rest_prefix='  ')")
    eq(wrap(text, 24, first_prefix="Greek: ", rest_prefix="       "),
       reference(text, 24, "Greek: ", "       "), "wrap(text, 24, 'Greek: ', 7 spaces)")


@test
def cli_widths_and_modes():
    for width in (20, 33, 40, 41, 42, 60, 79):
        for bullets in (False, True):
            args = ["wrap.py", "notes.txt", "--width", str(width)] + (["--bullets"] if bullets else [])
            proc = cli(*args)
            eq((proc.returncode, proc.stdout.splitlines()), (0, expected_cli(NOTES, width, bullets)),
               " ".join(args))


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
