#!/usr/bin/env python3
"""Completion check and cleanup for this project's task-panes queues (README.md here).

  queue_check.py done          # a queue's `done` command: TP_ID and TP_FIELD_* come from task-panes
  queue_check.py prune QUEUE   # in `refresh`: remove the worktree and temp directory of every finished task

A task is done when, on origin/main (fetch first):
- a commit message has the line `Queue-Task: <id>` — the task's merge; the newest such commit counts;
- the TODO item named by the task's `todo` field is checked in subagent-model-router/TODO.md;
- the task set's MANIFEST.json lists at least `min_tasks` tasks, when the task has that field;
- every GitHub check run on that merge commit finished as success, neutral or skipped. A later commit's runs do not
  count: a run checks only the files its own push changed.

Exit 0 done, 1 not yet, 2 a broken setup; the last line of output says why.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TASK_PANES_LIB = REPO / "task-panes" / "lib"
MAIN = "origin/main"
TODO = "subagent-model-router/TODO.md"
MANIFEST = "subagent-model-router/eval/taskset/MANIFEST.json"
GREEN = {"success", "neutral", "skipped"}
PENDING_TTL = 240  # seconds any answer but green is reused: unauthenticated API calls are limited to 60 an hour
TEMP_ROOT = Path("/var/tmp")  # prune deletes a task's directory only below this


class NotYet(Exception):
    """The task is not finished; the message says what is missing."""


class Broken(Exception):
    """The queue, the repository or the TODO list is not set up the way this check expects."""


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd or REPO), *args], capture_output=True, text=True, timeout=60)


def show(path: str) -> str:
    proc = git("show", f"{MAIN}:{path}")
    if proc.returncode != 0:
        raise Broken(f"{path} is not on {MAIN}")
    return proc.stdout


def merge_commit(task_id: str) -> str:
    """The newest commit on origin/main whose message has the line `Queue-Task: <task_id>`."""
    line = f"Queue-Task: {task_id}"
    proc = git("log", MAIN, "-F", f"--grep={line}", "--format=%H%x1f%B%x1e")
    if proc.returncode != 0:
        raise Broken(f"git log {MAIN}: {proc.stderr.strip()}")
    for record in proc.stdout.split("\x1e"):
        sha, _, body = record.strip().partition("\x1f")
        if any(text.strip() == line for text in body.splitlines()):
            return sha
    raise NotYet(f"not merged: no commit on {MAIN} has the line '{line}'")


def todo_checked(title: str) -> None:
    for line in show(TODO).splitlines():
        text = line.strip()
        if text.startswith("- [") and f"**{title}**" in text:
            if text.startswith(("- [x]", "- [X]")):
                return
            raise NotYet(f"TODO item '{title}' is not checked on {MAIN}")
    raise Broken(f"{TODO} on {MAIN} has no item **{title}**")


def manifest_size(minimum: int) -> None:
    try:
        count = len(json.loads(show(MANIFEST)).get("tasks", {}))
    except (ValueError, AttributeError) as exc:
        raise NotYet(f"{MANIFEST} on {MAIN} is not valid JSON: {exc}") from None
    if count < minimum:
        raise NotYet(f"{MANIFEST} on {MAIN} lists {count} tasks, this task needs {minimum}")


def github_repo() -> str:
    url = git("remote", "get-url", "origin").stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise Broken(f"origin is not a GitHub repository: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def fetch_checks(sha: str) -> tuple[str, str]:
    """("success" | "failure" | "pending" | "unknown", detail) from GitHub's check runs."""
    url = f"https://api.github.com/repos/{github_repo()}/commits/{sha}/check-runs?per_page=100"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "agent-plugins-queue-check"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            runs = json.load(response).get("check_runs", [])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return "unknown", f"cannot read CI state: {exc}"
    latest: dict[str, dict] = {}
    for run in runs:  # a re-run adds a run with the same name; the newest one counts
        if run.get("name") not in latest or run.get("id", 0) > latest[run["name"]].get("id", 0):
            latest[run.get("name")] = run
    if not latest:
        return "pending", "no check runs yet"
    waiting = sorted(n for n, r in latest.items() if r.get("status") != "completed")
    if waiting:
        return "pending", "running: " + ", ".join(waiting)
    failed = sorted(f"{n} ({r.get('conclusion')})" for n, r in latest.items() if r.get("conclusion") not in GREEN)
    if failed:
        return "failure", "not green: " + ", ".join(failed)
    return "success", f"{len(latest)} check runs green"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "agent-plugins-queues" / "ci"


def ci_state(sha: str) -> tuple[str, str]:
    """fetch_checks with a cache: a green answer is final, any other is reused for PENDING_TTL seconds."""
    path = cache_dir() / f"{sha}.json"
    try:
        cached = json.loads(path.read_text())
        if cached["state"] == "success" or time.time() - cached["at"] < PENDING_TTL:
            return cached["state"], cached["detail"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    state, detail = fetch_checks(sha)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps({"state": state, "detail": detail, "at": time.time()}))
    except OSError:
        pass
    return state, detail


def ci_green(sha: str) -> str:
    state, detail = ci_state(sha)
    if state == "success":
        return f"CI green on {sha[:12]}"
    if state == "failure":
        raise NotYet(f"CI {detail} on {sha[:12]}: fix it and merge again with the Queue-Task line, "
                     "or have the owner re-run a cancelled run")
    raise NotYet(f"CI on {sha[:12]}: {detail}")


def verdict(task_id: str, fields: dict[str, str]) -> str:
    """The reason the task is done, or NotYet / Broken."""
    sha = merge_commit(task_id)
    if fields.get("todo"):
        todo_checked(fields["todo"])
    if fields.get("min_tasks"):
        try:
            minimum = int(fields["min_tasks"])
        except ValueError:
            raise Broken(f"min_tasks of {task_id} is not a number: {fields['min_tasks']!r}") from None
        manifest_size(minimum)
    return f"done: merged in {sha[:12]}, {ci_green(sha)}"


def env_fields() -> dict[str, str]:
    prefix = "TP_FIELD_"
    return {k[len(prefix):].lower(): v for k, v in os.environ.items() if k.startswith(prefix)}


def cmd_done() -> int:
    task_id = os.environ.get("TP_ID")
    if not task_id:
        print("TP_ID is not set: run this as a task-panes command, or set TP_ID and TP_FIELD_* yourself")
        return 2
    try:
        print(verdict(task_id, env_fields()))
        return 0
    except NotYet as exc:
        print(exc)
        return 1
    except Broken as exc:
        print(exc)
        return 2


def remove_task_dir(root: Path, slug: str) -> bool:
    """Delete <TEMP_ROOT>/<session dir>/<slug> and the session dir once it is empty; nothing else."""
    root = root.resolve()
    if root.name != slug or root.parent.parent != TEMP_ROOT.resolve():
        return False
    shutil.rmtree(root)
    try:
        root.parent.rmdir()
    except OSError:
        pass
    return True


def cmd_prune(queue_path: str) -> int:
    sys.path.insert(0, str(TASK_PANES_LIB))
    from tp_queue import QueueError, load

    try:
        queue = load(queue_path)
    except QueueError as exc:
        print(exc)
        return 2
    for task in queue.tasks:
        paths = queue.paths(task)
        if not paths.worktree.exists():
            continue
        try:
            verdict(task.id, task.fields)
        except (NotYet, Broken):
            continue
        if git("status", "--porcelain", cwd=paths.worktree).stdout.strip():
            print(f"{task.id}: kept {paths.worktree}: uncommitted changes")
            continue
        tip = git("rev-parse", "--verify", "--quiet", f"refs/heads/{paths.branch}").stdout.strip()
        if tip and git("merge-base", "--is-ancestor", tip, MAIN).returncode != 0:
            print(f"{task.id}: kept {paths.worktree}: branch {paths.branch} has commits not on {MAIN}")
            continue
        removed = git("worktree", "remove", str(paths.worktree))
        if removed.returncode != 0:
            print(f"{task.id}: kept {paths.worktree}: {removed.stderr.strip()}")
            continue
        if tip:
            git("branch", "-D", paths.branch)
        gone = remove_task_dir(paths.worktree.parent, paths.slug)
        print(f"{task.id}: removed {paths.worktree}" + (f" and {paths.worktree.parent}" if gone else ""))
    return 0


def main(argv: list[str]) -> int:
    if argv == ["done"]:
        return cmd_done()
    if len(argv) == 2 and argv[0] == "prune":
        return cmd_prune(argv[1])
    print("usage: queue_check.py done | prune QUEUE")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
