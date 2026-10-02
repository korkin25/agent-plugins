#!/usr/bin/env python3
"""code-11: topological order with cycle reporting; hidden tests compare with the reference and validate reported cycles.

The check copies the workdir into a fresh directory under TMPDIR and runs hidden_tests.py there in a subprocess with
its own timeout: once on the reference in solution/, which yields the expected results, and once on the subagent's
copy. Any difference, a crash or a hang is a fail.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

TASK = Path(__file__).resolve().parent
MODULE = "toposort.py"
REFERENCE_TIMEOUT = 20  # seconds for the reference run
CANDIDATE_TIMEOUT = 10  # seconds for the run on the subagent's code


def kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_tests(code: Path, scratch: Path, name: str, timeout: int):
    """Run the hidden tests on the module in code; return their result list or a reason string."""
    out = scratch / f"{name}.json"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(scratch), "TMPDIR": str(scratch),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, "-I", "-B", str(TASK / "hidden_tests.py"), str(code), str(out)],
                            cwd=code, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill(proc)
        return f"the hidden tests did not finish within {timeout} s"
    if proc.returncode != 0:
        lines = err.decode("utf-8", "replace").strip().splitlines() or ["no message"]
        return f"the hidden tests crashed (exit {proc.returncode}): {lines[-1][:200]}"
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"the hidden tests wrote no readable result ({type(exc).__name__})"


def show(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 160 else text[:157] + "..."


def main(workdir: Path) -> int:
    if not (workdir / MODULE).is_file():
        print(f"{MODULE} is missing")
        return 1
    scratch = Path(tempfile.mkdtemp(prefix="code-11-"))
    try:
        work = scratch / "work"
        try:
            shutil.copytree(workdir, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except Exception as exc:  # noqa: BLE001 - an uncopyable workdir is the subagent's failure
            print(f"cannot copy the workdir: {type(exc).__name__}")
            return 1
        reference = scratch / "reference"
        shutil.copytree(TASK / "solution", reference)
        expected = run_tests(reference, scratch, "expected", REFERENCE_TIMEOUT)
        if not isinstance(expected, list):
            print(f"check error: the reference solution failed: {expected}")
            return 2
        actual = run_tests(work, scratch, "actual", CANDIDATE_TIMEOUT)
        if not isinstance(actual, list):
            print(actual)
            return 1
        names = [item.get("case") if isinstance(item, dict) else None for item in actual]
        if names != [item["case"] for item in expected]:
            print("the hidden tests returned a malformed result")
            return 1
        for want, got in zip(expected, actual):
            if got.get("result") != want["result"]:
                print(f"hidden case {want['case']}: got {show(got.get('result'))}, expected {show(want['result'])}")
                return 1
        print(f"pass: {len(expected)} hidden cases")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
