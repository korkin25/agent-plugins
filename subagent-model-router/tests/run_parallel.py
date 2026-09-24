#!/usr/bin/env python3
"""Run the plugin's tests in parallel, one `python3 -m unittest <module.Class>` process per test class.

python3 -B tests/run_parallel.py [-j N] [Class ...] — exits 1 if any class fails or runs fewer tests than found.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def discover():
    """({"module.Class": number of tests}, [loader errors]) — what `unittest discover` would run here."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(TESTS))
    counts, errors = {}, []

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            elif type(item).__module__ == "unittest.loader":  # a module that failed to import
                errors.append(item)
            else:
                name = f"{type(item).__module__}.{type(item).__qualname__}"
                counts[name] = counts.get(name, 0) + 1

    walk(unittest.TestLoader().discover(str(TESTS), top_level_dir=str(TESTS)))
    return counts, errors


def run(name, expected):
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-m", "unittest", name], cwd=TESTS, capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    match = re.search(r"^Ran (\d+) tests? in ", output, re.M)
    ran = int(match.group(1)) if match else 0
    return name, proc.returncode == 0 and ran == expected, ran, time.monotonic() - started, output


def main():
    parser = argparse.ArgumentParser(description="Run the tests in parallel, one process per test class.")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="parallel processes (default: 4)")
    parser.add_argument("classes", nargs="*", help="only these classes, as Class or module.Class")
    args = parser.parse_args()
    counts, errors = discover()
    if errors:
        unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(unittest.TestSuite(errors))
        print("FAILED: some test modules do not import")
        return 1
    selected = sorted(counts, key=lambda n: -counts[n])
    if args.classes:
        wanted = set(args.classes)
        selected = [n for n in selected if n in wanted or n.split(".")[-1] in wanted]
        missing = wanted - set(selected) - {n.split(".")[-1] for n in selected}
        if missing:
            print(f"FAILED: no such test class: {', '.join(sorted(missing))}")
            return 1
    started, failed, total = time.monotonic(), [], 0
    print(f"{sum(counts[n] for n in selected)} tests in {len(selected)} classes, {max(1, args.jobs)} at a time",
          flush=True)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(run, name, counts[name]) for name in selected]
        for future in as_completed(futures):
            name, ok, ran, elapsed, output = future.result()
            total += ran
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {ran}/{counts[name]} tests, {elapsed:.1f} s", flush=True)
            if not ok:
                failed.append(name)
                print(output, flush=True)
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    # Public check annotations keep test failures inspectable without downloading logs.
                    detail = output[-12000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                    print(f"::error title={name}::{detail}", flush=True)
    print(f"Ran {total} tests in {time.monotonic() - started:.1f} s: "
          + ("OK" if not failed else f"FAILED ({', '.join(failed)})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
