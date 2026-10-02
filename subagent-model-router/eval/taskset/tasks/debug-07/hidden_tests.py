"""Hidden tests for debug-07, run by check.py: python3 -I -B hidden_tests.py WORKDIR TOKEN.

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
import io

BOM = "\ufeff"


def reference(text, city=None):
    rows = list(csv.reader(io.StringIO(text.removeprefix(BOM), newline="")))
    header = [cell.strip() for cell in rows[0]]
    result = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        contact = {c: row[header.index(c)].strip() for c in ("name", "email", "city")}
        if city is None or contact["city"].casefold() == city.casefold():
            result.append(f"{contact['name']} <{contact['email']}>")
    return result


EXPORT = (WORK / "export.csv").read_bytes().decode("utf-8")

FILES = [
    BOM + "email,name,city\r\nlev@example.org,Лев,Сочи\r\nmila@example.org,Мила,сочи\r\n",
    BOM + "city,name,email\nТула,Нина,nina@example.org\n\nОмск,Олег,oleg@example.org\n",
    BOM + " name ,email,city,note\nПётр,petr@example.org,Тула,\"a, b\"\n",
    "name,email,city\nРоза,roza@example.org,Тула\n",
    "city,email,name\r\nОмск,stas@example.org,Стас\r\n",
]


def run_tool(text, *extra):
    path = scratch_file("contacts.csv", text.encode("utf-8"))
    return cli("contacts.py", str(path), *extra)


@test
def reported_command():
    proc = cli("contacts.py", "export.csv")
    eq((proc.returncode, proc.stdout.splitlines()), (0, reference(EXPORT)), "contacts.py export.csv")


@test
def reported_file_other_modes():
    proc = cli("contacts.py", "export.csv", "--city", "КАЗАНЬ")
    eq((proc.returncode, proc.stdout.splitlines()), (0, reference(EXPORT, "казань")), "--city КАЗАНЬ")
    proc = cli("contacts.py", "export.csv", "--check")
    eq((proc.returncode, proc.stdout.strip()), (0, "ok"), "contacts.py export.csv --check")


@test
def files_with_and_without_bom():
    for text in FILES:
        proc = run_tool(text)
        eq((proc.returncode, proc.stdout.splitlines()), (0, reference(text)), f"listing of {text!r}")
        proc = run_tool(text, "--city", "тула")
        eq((proc.returncode, proc.stdout.splitlines()), (0, reference(text, "тула")), f"--city тула on {text!r}")
        proc = run_tool(text, "--check")
        eq((proc.returncode, proc.stdout.strip()), (0, "ok"), f"--check on {text!r}")


@test
def library_functions():
    contacts = load("contacts")
    path = scratch_file("c.csv", (BOM + "email,city,name\nzoya@example.org,Тверь,Зоя\n").encode("utf-8"))
    eq(contacts.load(str(path)), [{"name": "Зоя", "email": "zoya@example.org", "city": "Тверь"}], "load()")
    eq(contacts.read_header(str(path)), ["email", "city", "name"], "read_header()")


@test
def missing_columns_still_reported():
    cases = [
        (BOM + "name,phone\nЯна,123\n", "ошибка: нет колонок: email, city"),
        (BOM + "email,city\nyana@example.org,Тула\n", "ошибка: нет колонок: name"),
        ("fullname,email,city\nЯна,yana@example.org,Тула\n", "ошибка: нет колонок: name"),
    ]
    for text, message in cases:
        for extra in ((), ("--check",)):
            proc = run_tool(text, *extra)
            eq((proc.returncode, proc.stderr.strip(), proc.stdout), (1, message, ""), f"{extra} on {text!r}")


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
