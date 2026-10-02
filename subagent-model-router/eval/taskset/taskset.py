#!/usr/bin/env python3
"""The frozen task set for the paired strategy eval: list, prepare, check, validate and freeze task packets.

python3 taskset.py list [--domain D] [--json]   # the tasks and the domain x difficulty table
python3 taskset.py prepare ID DEST              # copy the workspace to DEST, print the packet for DEST
python3 taskset.py check ID WORKDIR             # run the task's check: exit 0 pass, 1 fail, 2 check error
python3 taskset.py validate [ID ...] [-j N]     # untouched work fails, the solution passes, broken variants fail
python3 taskset.py manifest [--write]           # compare (or rewrite) MANIFEST.json with the task files

Standard library only; Python 3.11+. The layout and the rules are in README.md next to this file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks"
MANIFEST = ROOT / "MANIFEST.json"

DOMAINS = ("math", "logic", "code", "tooling", "debug", "review", "text", "data")
LANGUAGES = ("en", "ru")
SOURCES = ("synthetic",)
REQUIRED = {"id", "domain", "difficulty", "title", "language", "outputs", "source", "check_timeout_seconds", "tags"}
OPTIONAL = {"notes"}
RESERVED = {"task.json", "packet.md", "check.py", "workspace", "solution", "broken"}
ID_RE = re.compile(r"^([a-z]+)-(\d{2})$")
PLACEHOLDER = "{workdir}"
MAX_PACKET_CHARS = 12000
MAX_TASK_BYTES = 256 * 1024
SKIP = {"__pycache__", ".DS_Store"}


@dataclass
class Outcome:
    status: str  # pass | fail | timeout | error
    reason: str
    seconds: float = 0.0


def files_under(path: Path):
    """Regular files under path, sorted by their POSIX relative path; caches are skipped."""
    found = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP)
        for name in filenames:
            if name in SKIP or name.endswith(".pyc"):
                continue
            found.append(Path(dirpath) / name)
    return sorted(found, key=lambda p: p.relative_to(path).as_posix())


def task_hash(task_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in files_under(task_dir):
        rel = path.relative_to(task_dir).as_posix()
        digest.update(f"{rel}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return digest.hexdigest()


def task_ids():
    if not TASKS.is_dir():
        return []
    return sorted(p.name for p in TASKS.iterdir() if p.is_dir() and p.name not in SKIP)


def load(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "task.json").read_text(encoding="utf-8"))


def structure_errors(task_id: str) -> list[str]:
    """Problems with the files themselves, found without running anything."""
    task_dir = TASKS / task_id
    errors = []
    match = ID_RE.match(task_id)
    if not match or match.group(1) not in DOMAINS:
        errors.append(f"directory name {task_id!r} is not <domain>-NN with a known domain")
    for name in ("task.json", "packet.md", "check.py"):
        if not (task_dir / name).is_file():
            errors.append(f"{name} is missing")
    if errors:
        return errors
    try:
        meta = load(task_id)
    except (OSError, ValueError) as exc:
        return [f"task.json does not parse: {exc}"]
    if not isinstance(meta, dict):
        return ["task.json is not an object"]
    missing, unknown = REQUIRED - meta.keys(), meta.keys() - REQUIRED - OPTIONAL
    if missing:
        errors.append(f"task.json lacks {sorted(missing)}")
    if unknown:
        errors.append(f"task.json has unknown keys {sorted(unknown)}")
    if meta.get("id") != task_id:
        errors.append(f"task.json id {meta.get('id')!r} differs from the directory name")
    if match and meta.get("domain") != match.group(1):
        errors.append(f"domain {meta.get('domain')!r} differs from the id prefix")
    if meta.get("difficulty") not in (1, 2, 3):
        errors.append("difficulty must be 1, 2 or 3")
    if meta.get("language") not in LANGUAGES:
        errors.append(f"language must be one of {LANGUAGES}")
    if meta.get("source") not in SOURCES:
        errors.append(f"source must be one of {SOURCES}")
    if not isinstance(meta.get("title"), str) or not meta.get("title", "").strip():
        errors.append("title must be a non-empty string")
    timeout = meta.get("check_timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        errors.append("check_timeout_seconds must be an integer from 1 to 120")
    tags = meta.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
        errors.append("tags must be a list of non-empty strings")
    outputs = meta.get("outputs")
    if not isinstance(outputs, list) or not outputs or not all(isinstance(o, str) and o for o in outputs):
        errors.append("outputs must be a non-empty list of relative paths")
        outputs = []
    for out in outputs:
        if Path(out).is_absolute() or ".." in Path(out).parts:
            errors.append(f"output {out!r} must be a relative path inside the workdir")

    try:
        packet = (task_dir / "packet.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"packet.md is not readable UTF-8: {exc}")
        packet = ""
    if PLACEHOLDER not in packet:
        errors.append(f"packet.md never mentions {PLACEHOLDER}")
    if len(packet) > MAX_PACKET_CHARS:
        errors.append(f"packet.md has {len(packet)} characters, more than {MAX_PACKET_CHARS}")
    for out in outputs:
        if out not in packet:
            errors.append(f"packet.md never names the output {out!r}")

    solution = task_dir / "solution"
    if not solution.is_dir() or not files_under(solution):
        errors.append("solution/ is missing or empty")
    broken = task_dir / "broken"
    variants = sorted(p for p in broken.iterdir() if p.is_dir() and p.name not in SKIP) if broken.is_dir() else []
    if not variants:
        errors.append("broken/ has no variant directory")
    for variant in variants:
        if not files_under(variant):
            errors.append(f"broken/{variant.name}/ is empty")
    if broken.is_dir() and any(p.is_file() for p in broken.iterdir() if p.name not in SKIP):
        errors.append("broken/ holds files directly; put each variant in broken/<name>/")
    if meta.get("difficulty") == 3 and len(variants) < 2:
        errors.append("a difficulty-3 task needs at least two broken variants")

    total = 0
    for path in task_dir.rglob("*"):
        if path.is_symlink():
            errors.append(f"{path.relative_to(task_dir)} is a symlink")
        elif path.is_file() and not path.name.endswith(".pyc"):
            total += path.stat().st_size
    if total > MAX_TASK_BYTES:
        errors.append(f"the task holds {total} bytes, more than {MAX_TASK_BYTES}")
    return errors


def overlay(src: Path, dest: Path):
    for path in files_under(src):
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def prepare(task_id: str, dest: Path) -> str:
    """Copy the workspace into dest (absent or empty) and return the packet written for dest."""
    dest = dest.resolve()
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise SystemExit(f"{dest} exists and is not an empty directory")
    dest.mkdir(parents=True, exist_ok=True)
    workspace = TASKS / task_id / "workspace"
    if workspace.is_dir():
        overlay(workspace, dest)
    packet = (TASKS / task_id / "packet.md").read_text(encoding="utf-8")
    return packet.replace(PLACEHOLDER, str(dest))


def run_check(task_id: str, workdir: Path, scratch: Path | None = None) -> Outcome:
    """Run check.py on workdir in a clean environment, with the task's timeout."""
    import time

    meta = load(task_id)
    own = scratch is None
    scratch = Path(tempfile.mkdtemp(prefix=f"check-{task_id}-")) if own else scratch
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    command = [sys.executable, "-I", "-B", str(TASKS / task_id / "check.py"), str(workdir.resolve())]
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=scratch, env=env, capture_output=True, text=True,
                              errors="replace", timeout=meta["check_timeout_seconds"])
    except subprocess.TimeoutExpired:
        return Outcome("timeout", f"check ran longer than {meta['check_timeout_seconds']} s",
                       time.monotonic() - started)
    finally:
        if own:
            shutil.rmtree(scratch, ignore_errors=True)
    seconds = time.monotonic() - started
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    reason = lines[-1].strip() if lines else ""
    if proc.returncode == 0:
        return Outcome("pass", reason, seconds)
    if proc.returncode == 1:
        return Outcome("fail", reason, seconds)
    tail = (proc.stderr.strip().splitlines() or [""])[-1]
    return Outcome("error", f"exit {proc.returncode}: {tail or reason}", seconds)


def trial(task_id: str, overlays: list[Path], base: Path) -> Outcome:
    workdir = base / "work"
    scratch = base / "scratch"
    shutil.rmtree(workdir, ignore_errors=True)
    shutil.rmtree(scratch, ignore_errors=True)
    workdir.mkdir(parents=True)
    scratch.mkdir(parents=True)
    workspace = TASKS / task_id / "workspace"
    if workspace.is_dir():
        overlay(workspace, workdir)
    for layer in overlays:
        overlay(layer, workdir)
    return run_check(task_id, workdir, scratch)


def validate_task(task_id: str) -> tuple[str, list[str], float]:
    errors = structure_errors(task_id)
    if errors:
        return task_id, errors, 0.0
    task_dir = TASKS / task_id
    base = Path(tempfile.mkdtemp(prefix=f"validate-{task_id}-"))
    slowest = 0.0
    try:
        runs = [("untouched workspace", [], "fail"),
                ("solution", [task_dir / "solution"], "pass"),
                ("solution, second run", [task_dir / "solution"], "pass")]
        for variant in sorted(p for p in (task_dir / "broken").iterdir() if p.is_dir() and p.name not in SKIP):
            runs.append((f"broken/{variant.name}", [variant], "fail"))
        for label, layers, expected in runs:
            outcome = trial(task_id, layers, base)
            slowest = max(slowest, outcome.seconds)
            if outcome.status != expected:
                errors.append(f"{label}: expected {expected}, got {outcome.status} ({outcome.reason})")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return task_id, errors, slowest


def manifest_data() -> dict:
    tasks = {}
    for task_id in task_ids():
        meta = load(task_id)
        tasks[task_id] = {"sha256": task_hash(TASKS / task_id), "domain": meta["domain"],
                          "difficulty": meta["difficulty"], "language": meta["language"]}
    combined = hashlib.sha256("".join(f"{k}\0{v['sha256']}\n" for k, v in tasks.items()).encode()).hexdigest()
    return {"tasks": tasks, "sha256": combined}


def table(metas: list[dict]) -> str:
    rows = [f"{'domain':<9} {'d1':>4} {'d2':>4} {'d3':>4} {'ru':>4} {'all':>5}"]
    totals = [0, 0, 0, 0, 0]
    for domain in DOMAINS:
        group = [m for m in metas if m["domain"] == domain]
        counts = [sum(m["difficulty"] == d for m in group) for d in (1, 2, 3)]
        counts += [sum(m["language"] == "ru" for m in group), len(group)]
        totals = [a + b for a, b in zip(totals, counts)]
        rows.append(f"{domain:<9} {counts[0]:>4} {counts[1]:>4} {counts[2]:>4} {counts[3]:>4} {counts[4]:>5}")
    rows.append(f"{'total':<9} {totals[0]:>4} {totals[1]:>4} {totals[2]:>4} {totals[3]:>4} {totals[4]:>5}")
    return "\n".join(rows)


def cmd_list(args) -> int:
    metas = [load(t) for t in task_ids()]
    if args.domain:
        metas = [m for m in metas if m["domain"] == args.domain]
    if args.json:
        print(json.dumps(metas, ensure_ascii=False, indent=2))
        return 0
    for m in metas:
        print(f"{m['id']:<11} d{m['difficulty']} {m['language']}  {m['title']}")
    print()
    print(table(metas))
    return 0


def cmd_prepare(args) -> int:
    if args.id not in task_ids():
        raise SystemExit(f"no task {args.id}")
    sys.stdout.write(prepare(args.id, Path(args.dest)))
    return 0


def cmd_check(args) -> int:
    if args.id not in task_ids():
        raise SystemExit(f"no task {args.id}")
    outcome = run_check(args.id, Path(args.workdir))
    print(json.dumps({"id": args.id, "status": outcome.status, "reason": outcome.reason,
                      "seconds": round(outcome.seconds, 3)}, ensure_ascii=False))
    return {"pass": 0, "fail": 1, "timeout": 1}.get(outcome.status, 2)


def cmd_validate(args) -> int:
    ids = args.ids or task_ids()
    unknown = [t for t in ids if not (TASKS / t).is_dir()]
    if unknown:
        raise SystemExit(f"no such tasks: {' '.join(unknown)}")
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for task_id, errors, slowest in pool.map(validate_task, ids):
            if errors:
                failed += 1
                print(f"FAIL {task_id}")
                for error in errors:
                    print(f"     {error}")
            elif args.verbose:
                print(f"ok   {task_id} (slowest check {slowest:.2f} s)")
    print(f"{len(ids) - failed}/{len(ids)} tasks valid")
    return 1 if failed else 0


def cmd_manifest(args) -> int:
    current = manifest_data()
    if args.write:
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
        data = {"version": recorded.get("version", 1), "frozen": recorded.get("frozen", ""),
                "retired": recorded.get("retired", {}), **current}
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"MANIFEST.json written: {len(current['tasks'])} tasks, set {current['sha256']}")
        return 0
    if not MANIFEST.exists():
        print("MANIFEST.json is missing")
        return 1
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    problems = []
    old, new = recorded.get("tasks", {}), current["tasks"]
    for task_id in sorted(old.keys() | new.keys()):
        if task_id not in new:
            problems.append(f"{task_id}: in MANIFEST.json, not in tasks/")
        elif task_id not in old:
            problems.append(f"{task_id}: in tasks/, not in MANIFEST.json")
        elif old[task_id] != new[task_id]:
            problems.append(f"{task_id}: files differ from MANIFEST.json")
    if recorded.get("sha256") != current["sha256"]:
        problems.append("the set hash differs from MANIFEST.json")
    for task_id in recorded.get("retired", {}):
        if task_id in new:
            problems.append(f"{task_id}: retired, yet still in tasks/")
    for problem in problems:
        print(problem)
    print("MANIFEST.json matches the tasks" if not problems else f"{len(problems)} manifest problems")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("list", help="list the tasks")
    p.add_argument("--domain", choices=DOMAINS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("prepare", help="copy a task's workspace and print its packet")
    p.add_argument("id")
    p.add_argument("dest")
    p.set_defaults(func=cmd_prepare)
    p = sub.add_parser("check", help="run a task's check on a workdir")
    p.add_argument("id")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("validate", help="validate tasks against their solutions and broken variants")
    p.add_argument("ids", nargs="*")
    p.add_argument("-j", "--jobs", type=int, default=min(8, os.cpu_count() or 1))
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("manifest", help="compare or rewrite MANIFEST.json")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_manifest)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
