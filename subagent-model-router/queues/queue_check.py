#!/usr/bin/env python3
"""Completion check and cleanup for this project's task-panes queues (README.md here).

  queue_check.py done          # a queue's `done` command: TP_ID and TP_FIELD_* come from task-panes
  queue_check.py prune QUEUE   # in `refresh`: remove the worktree and temp directory of every finished task

A task is done when, on origin/main (fetch first):
- a commit on its first-parent line has the message line `Queue-Task: <id>` — the task's merge; the newest counts;
- the TODO item named by the task's `todo` field is checked in subagent-model-router/TODO.md;
- the task set's MANIFEST.json lists at least `min_tasks` tasks, when the task has that field;
- every GitHub Actions run on main for that merge commit finished as success, neutral or skipped. A later commit's
  runs do not count: validate.yml checks what a push changed, and for a Queue-Task merge that is everything since
  the task's first merge.

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
    # Agents can write refs/replace in the shared .git (the sandbox makes it writable): read the real commits.
    return subprocess.run(["git", "--no-replace-objects", "-C", str(cwd or REPO), *args], capture_output=True,
                          text=True, timeout=60)


def show(path: str) -> str:
    proc = git("show", f"{MAIN}:{path}")
    if proc.returncode != 0:
        raise Broken(f"{path} is not on {MAIN}")
    return proc.stdout


def merge_commit(task_id: str) -> str:
    """The newest commit on the first-parent line of origin/main whose message has the line `Queue-Task: <id>`."""
    line = f"Queue-Task: {task_id}"
    proc = git("log", MAIN, "--first-parent", "-F", f"--grep={line}", "--format=%H%x1f%B%x1e")
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
        data = json.loads(show(MANIFEST))
    except ValueError as exc:
        raise NotYet(f"{MANIFEST} on {MAIN} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
        raise NotYet(f"{MANIFEST} on {MAIN} has no `tasks` object")
    count = len(data["tasks"])
    if count < minimum:
        raise NotYet(f"{MANIFEST} on {MAIN} lists {count} tasks, this task needs {minimum}")


def github_repo() -> str:
    url = git("remote", "get-url", "origin").stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        raise Broken(f"origin is not a GitHub repository: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def fetch_runs(sha: str) -> tuple[str, str]:
    """("success" | "failure" | "pending" | "unknown", detail) from the GitHub Actions runs on main for `sha`.

    Workflow runs, not check runs: a run waiting for its concurrency group is listed before it has any check run."""
    url = f"https://api.github.com/repos/{github_repo()}/actions/runs?head_sha={sha}&per_page=100"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "agent-plugins-queue-check"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
        runs = data["workflow_runs"]
        total = data.get("total_count", len(runs))
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
        return "unknown", f"cannot read CI state: {exc}"
    if total > len(runs):
        return "unknown", f"{total} runs on {sha[:12]}, more than one page"
    latest: dict[object, dict] = {}
    for run in runs:
        if run.get("head_branch") != "main":  # the same commit pushed to another branch has runs of its own
            continue
        key = run.get("workflow_id")  # a re-run reuses its run; a dispatch adds one, and the newest counts
        if key not in latest or run.get("id", 0) > latest[key].get("id", 0):
            latest[key] = run
    if not latest:
        return "pending", "no workflow runs on main yet"
    names = {key: run.get("name") or str(key) for key, run in latest.items()}
    waiting = sorted(names[k] for k, r in latest.items() if r.get("status") != "completed")
    if waiting:
        return "pending", "running: " + ", ".join(waiting)
    failed = sorted(f"{names[k]} ({r.get('conclusion')})" for k, r in latest.items()
                    if r.get("conclusion") not in GREEN)
    if failed:
        return "failure", "not green: " + ", ".join(failed)
    return "success", f"{len(latest)} workflow runs green"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "agent-plugins-queues" / "ci"


def ci_state(sha: str) -> tuple[str, str]:
    """fetch_runs with a cache: a green answer is final, any other is reused for PENDING_TTL seconds."""
    path = cache_dir() / f"{sha}.json"
    try:
        cached = json.loads(path.read_text())
        if cached["state"] == "success" or time.time() - cached["at"] < PENDING_TTL:
            return cached["state"], cached["detail"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    state, detail = fetch_runs(sha)
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
        raise NotYet(f"CI {detail} on {sha[:12]}: fix a failure and merge again with the Queue-Task line; "
                     "ask the owner to re-run a cancelled run")
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


def task_dir(paths) -> Path | None:
    """<TEMP_ROOT>/<session dir>/<slug>, the directory holding the task's worktree; None when it lies elsewhere."""
    root = paths.worktree.parent.resolve()
    if root.name == paths.slug and root.parent.parent == TEMP_ROOT.resolve():
        return root
    return None


def finished(queue) -> set[str]:
    """Tasks the runner has recorded as done, so their panes are closed. dry-run and status run `refresh` too."""
    try:
        state = json.loads((queue.state_dir / "state.json").read_text(encoding="utf-8"))
        return {task_id for task_id, st in state["tasks"].items()
                if isinstance(st, dict) and st.get("status") == "done" and not st.get("pane")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def unsaved(worktree: Path, branch: str) -> str | None:
    """Why removing the worktree and the branch would lose work, or None."""
    status = git("status", "--porcelain", cwd=worktree)
    if status.returncode != 0:
        return f"git status failed: {status.stderr.strip()}"
    if status.stdout.strip():
        return "uncommitted changes"
    head = git("rev-parse", "--verify", "--quiet", "HEAD", cwd=worktree).stdout.strip()
    tip = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").stdout.strip()
    for what, sha in (("the worktree's HEAD", head), (f"branch {branch}", tip)):
        if sha and git("merge-base", "--is-ancestor", sha, MAIN).returncode != 0:
            return f"{what} has commits not on {MAIN}"
    return None


def cmd_prune(queue_path: str) -> int:
    sys.path.insert(0, str(TASK_PANES_LIB))
    from tp_queue import QueueError, load

    try:
        queue = load(queue_path)
    except QueueError as exc:
        print(exc)
        return 2
    done = finished(queue)
    for task in queue.tasks:
        paths = queue.paths(task)
        if task.id not in done or not paths.worktree.exists():
            continue
        try:
            verdict(task.id, task.fields)
        except (NotYet, Broken):
            continue
        root = task_dir(paths)
        reason = unsaved(paths.worktree, paths.branch) if root else f"not in a task directory below {TEMP_ROOT}"
        if reason:
            print(f"{task.id}: kept {paths.worktree}: {reason}")
            continue
        removed = git("worktree", "remove", str(paths.worktree))
        if removed.returncode != 0:
            print(f"{task.id}: kept {paths.worktree}: {removed.stderr.strip()}")
            continue
        git("branch", "-D", paths.branch)
        shutil.rmtree(root, ignore_errors=True)
        try:
            root.parent.rmdir()  # the session directory, once its last task is gone
        except OSError:
            pass
        print(f"{task.id}: removed {paths.worktree}, branch {paths.branch} and {root}")
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
