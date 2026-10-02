#!/usr/bin/env python3
"""debug-10: summarize() handles any iterable, the read_scores generator included

Copies the workdir to a fresh directory under TMPDIR and runs hidden_tests.py (next to this file) on the copy in
a subprocess with its own timeout, so a hang or a crash of the subagent's code is a fail, never a check error.
"""
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ['stats.py', 'scores.py']  # the project files the hidden tests import or run
UNCHANGED = ['test_stats.py', 'results.txt']  # files the packet forbids changing; compared with workspace/
TIMEOUT = 6  # seconds for the whole hidden test run


def run_tests(workdir: Path) -> tuple[int, str]:
    for name in REQUIRED:
        if not (workdir / name).is_file():
            return 1, f"{name} is missing"
    for name in UNCHANGED:
        path = workdir / name
        if not path.is_file() or path.read_bytes() != (HERE / "workspace" / name).read_bytes():
            return 1, f"{name} was changed or removed"
    base = Path(tempfile.mkdtemp(prefix="debug-10-"))
    try:
        work = base / "work"
        shutil.copytree(workdir, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        home = base / "home"
        home.mkdir()
        token = secrets.token_hex(8)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        proc = subprocess.Popen([sys.executable, "-I", "-B", str(HERE / "hidden_tests.py"), str(work), token],
                                cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace", start_new_session=True)
        try:
            out, err = proc.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            proc.communicate()
            return 1, f"the hidden tests did not finish in {TIMEOUT} s (a hang?)"
        kill_group(proc)
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        if proc.returncode == 0 and lines and lines[-1] == f"ALL PASSED {token}":
            return 0, "pass"
        failures = [line for line in lines if line.startswith("FAIL ")]
        if failures:
            return 1, failures[-1][:400]
        tail = (err.strip().splitlines() or ["no output"])[-1]
        return 1, f"the hidden tests stopped with exit {proc.returncode}: {tail[:300]}"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check.py WORKDIR")
        return 2
    try:
        code, reason = run_tests(Path(sys.argv[1]))
    except Exception as exc:  # an unreadable or odd workdir is the subagent's failure
        code, reason = 1, f"could not run the hidden tests: {type(exc).__name__}: {exc}"
    print(reason)
    return code


if __name__ == "__main__":
    sys.exit(main())
