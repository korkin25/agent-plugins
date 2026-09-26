"""Runner engine: evaluate tasks, launch agents into tmux panes, verify completion itself."""
from __future__ import annotations

import fcntl
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import tp_sandbox
from tp_queue import Queue, QueueError, Task
from tp_tmux import CONTROL, LABEL_OPTION, TASK_OPTION, Pane, Tmux, TmuxError
from tp_tmux import socket_path as tmux_socket_path

# The agent starts from an empty environment: only these (plus the queue's pass_env) come from
# the runner, TERM and COLORTERM from its pane, TP_* from the task.
PASS_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SSH_AUTH_SOCK", "LANG", "LC_ALL", "LC_CTYPE")
PANE_ENV = ("TERM", "COLORTERM")
ACTIVE = ("running", "exited", "stopped")
LIGHT_SECONDS = 2.0


def agent_env(queue: Queue, source=None) -> dict:
    """The only variables an agent gets from the runner: PASS_ENV plus the queue's pass_env."""
    source = os.environ if source is None else source
    return {k: source[k] for k in (*PASS_ENV, *queue.pass_env) if k in source}


class RunnerError(Exception):
    """A runner problem with a message meant for the user."""


@dataclass
class Result:
    code: int | None
    reason: str
    stdout: str = ""


def run_command(cmd: str, cwd: Path, env: dict, timeout: float) -> Result:
    """Run a queue command with sh -c; code None means it could not run or timed out."""
    try:
        proc = subprocess.run(["sh", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Result(None, f"timed out after {timeout:g}s")
    except OSError as exc:
        return Result(None, f"could not run: {exc}")
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        lines = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip()]
    reason = lines[-1][:200] if lines else f"exit code {proc.returncode}"
    return Result(proc.returncode, reason, proc.stdout)


def make_private_dirs(path: Path) -> None:
    """Create path and any missing parents with mode 0700."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for part in reversed(missing):
        part.mkdir(mode=0o700)


class Store:
    """Runner state directory: state.json is written only by the runner holding runner.lock."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def ensure(self) -> None:
        make_private_dirs(self.root)

    def load(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"tasks": {}}
        except (OSError, ValueError) as exc:
            raise RunnerError(f"state file {self.state_path} is unreadable ({exc}); "
                              "move it away to start from a clean state") from None
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
            raise RunnerError(f"state file {self.state_path} has an unexpected shape; move it away")
        return data

    def save(self, state: dict) -> None:
        self.write_json(self.state_path, state)

    def file(self, kind: str, task_id: str) -> Path:
        return self.root / kind / f"{task_id}.json"

    def write_json(self, path: Path, data) -> None:
        make_private_dirs(path.parent)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def read_json(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def lock(self) -> int | None:
        """Take the runner lock; None when another runner holds it."""
        self.ensure()
        fd = os.open(self.root / "runner.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd

    def active_pid(self) -> int | None:
        """Pid of the live runner, or None when nobody holds the lock."""
        if not (self.root / "runner.lock").exists():
            return None
        fd = self.lock()
        if fd is not None:
            os.close(fd)
            return None
        try:
            return int((self.root / "runner.pid").read_text().strip())
        except (OSError, ValueError):
            return -1

    def log(self, message: str) -> None:
        self.ensure()
        with open(self.root / "runner.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


class Engine:
    def __init__(self, queue: Queue, tmux: Tmux, store: Store, bin_path: str, python: str = sys.executable,
                 out=None, dry: bool = False, clock=time.time):
        self.queue, self.tmux, self.store = queue, tmux, store
        self.bin_path, self.python, self.out, self.dry, self.clock = bin_path, python, out, dry, clock
        self.state = store.load()
        self.evals: dict[str, tuple[str, str]] = {}
        self.control: str | None = None
        self.dirty = False
        self.asked: set[str] = set()

    # ---- helpers
    def st(self, task_id: str) -> dict:
        return self.state["tasks"].setdefault(task_id, {"status": "pending"})

    def status_of(self, task_id: str) -> str:
        return self.state["tasks"].get(task_id, {}).get("status", "pending")

    def event(self, message: str) -> None:
        if self.dry:
            return
        self.store.log(message)
        if self.out:
            self.out(f"{time.strftime('%H:%M:%S')} {message}")

    def save(self) -> None:
        if not self.dry:
            self.store.save(self.state)

    def task_env(self, task: Task, session_id: str = "", dep: str | None = None) -> dict:
        ctx = self.queue.context(task, None, session_id)
        env = {"TP_ID": task.id, "TP_TITLE": task.title, "TP_SLUG": ctx["slug"], "TP_WORKTREE": ctx["worktree"],
               "TP_BRANCH": ctx["branch"], "TP_QUEUE": str(self.queue.path), "TP_QUEUE_DIR": str(self.queue.dir),
               "TP_SESSION": self.queue.session, "TP_SESSION_ID": session_id}
        for key, value in task.fields.items():
            env["TP_FIELD_" + re.sub(r"\W", "_", key).upper()] = value
        if dep is not None:
            env["TP_DEP"] = dep
        return env

    def command(self, name: str, task: Task | None = None, session_id: str = "", dep: str | None = None) -> Result:
        env = dict(os.environ)
        env.update(self.queue.env)
        if task is not None:
            env.update(self.task_env(task, session_id, dep))
        return run_command(self.queue.commands[name], self.queue.dir, env, self.queue.command_timeout)

    def done_check(self, task: Task) -> Result:
        return self.command("done", task, self.state["tasks"].get(task.id, {}).get("session_id", ""))

    def agent_for(self, task: Task) -> str | None:
        return self.queue.resolve_agent(task) or self.state["tasks"].get(task.id, {}).get("choice")

    # ---- evaluation
    def dependencies(self, task: Task) -> tuple[list[str] | None, tuple[str, str] | None]:
        deps = list(task.depends_on)
        if "dependencies" in self.queue.commands:
            r = self.command("dependencies", task)
            if r.code == 1:
                return None, ("waiting", r.reason)
            if r.code != 0:
                return None, ("error", f"dependencies command: {r.reason}")
            deps += [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        return list(dict.fromkeys(deps)), None

    def dependency_done(self, task: Task, dep: str) -> bool | None:
        if "dependency_done" in self.queue.commands:
            r = self.command("dependency_done", task, dep=dep)
            return {0: True, 1: False}.get(r.code)
        if any(t.id == dep for t in self.queue.tasks):
            return self.status_of(dep) == "done"
        return False

    def evaluate(self, task: Task) -> tuple[str, str]:
        """Status of a task that has not been launched: done, stopped, error, waiting, needs-agent, ready."""
        r = self.done_check(task)
        if r.code == 0:
            return "done", r.reason
        if r.code == 2:
            return "stopped", f"completion check failed: {r.reason}"
        if r.code != 1:
            return "error", f"completion check error: {r.reason}"
        deps, verdict = self.dependencies(task)
        if verdict:
            return verdict
        pending = []
        for dep in deps:
            ok = self.dependency_done(task, dep)
            if ok is None:
                return "error", f"dependency check for {dep} failed"
            if not ok:
                pending.append(dep)
        if pending:
            return "waiting", "waiting for " + ", ".join(pending)
        worktree = self.queue.paths(task).worktree
        note = f"not done: {r.reason}"
        if worktree.exists():
            rule = self.queue.on_existing_worktree(task)
            if rule == "stop":
                return "stopped", f"worktree already exists: {worktree}"
            if rule == "resume":
                note = f"will resume in existing worktree {worktree}"
        if self.agent_for(task) is None:
            return "needs-agent", f"{note}; choose an agent: " + " / ".join(self.queue.agents)
        return "ready", note

    # ---- transitions
    def set_label(self, pane: str | None, text: str) -> None:
        if pane and not self.dry:
            try:
                self.tmux.set_option(pane, LABEL_OPTION, text[:150])
            except TmuxError:
                pass

    def finish_done(self, task: Task, reason: str) -> None:
        st = self.st(task.id)
        self.store.write_json(self.store.file("verdict", task.id), {"status": "done", "reason": reason})
        if st.get("pane"):
            self.tmux.kill_pane(st["pane"])
        st.update(status="done", reason=reason, pane=None, finished=self.clock())
        self.dirty = True
        self.event(f"{task.id} done: {reason}")

    def stop(self, task: Task, reason: str) -> None:
        st = self.st(task.id)
        st.update(status="stopped", reason=reason, finished=self.clock())
        if st.get("pane"):
            self.store.write_json(self.store.file("verdict", task.id), {"status": "stopped", "reason": reason})
            self.set_label(st["pane"], f"{task.id} STOPPED: {reason}")
        self.event(f"{task.id} stopped: {reason}")

    def verify_exit(self, task: Task) -> None:
        st = self.st(task.id)
        code = st.get("exit_code")
        how = f"agent exited (code {code})" if code is not None else "agent pane closed"
        r = self.done_check(task)
        if r.code == 0:
            self.finish_done(task, r.reason)
        elif r.code == 1:
            self.stop(task, f"{how}, but the completion check says not done: {r.reason}")
        elif r.code == 2:
            self.stop(task, f"{how}; completion check failed: {r.reason}")
        else:
            st["reason"] = f"{how}; completion check error, will retry: {r.reason}"

    def check_active(self, task: Task) -> None:
        st = self.st(task.id)
        if st["status"] == "exited":
            self.verify_exit(task)
            return
        r = self.done_check(task)
        if r.code == 0:
            self.finish_done(task, r.reason)
        elif st["status"] != "running":
            return
        elif r.code == 2:
            self.stop(task, f"completion check failed while the agent runs: {r.reason}")
        elif r.code != 1:
            st["reason"] = f"completion check error, will retry: {r.reason}"

    # ---- cycles
    def heavy(self) -> None:
        """Refresh project data, verify active tasks and re-evaluate the rest."""
        if "refresh" in self.queue.commands:
            r = self.command("refresh")
            if r.code != 0:
                self.event(f"refresh command failed: {r.reason}")
        for task in self.queue.tasks:
            status = self.status_of(task.id)
            if status == "done":
                pass
            elif status in ACTIVE and not self.dry:
                self.check_active(task)
            elif status in ACTIVE:
                pass
            else:
                status, reason = self.evaluate(task)
                if status in ("done", "stopped") and not self.dry:
                    if status == "done":
                        self.st(task.id).update(status="done", reason=reason, finished=self.clock())
                        self.dirty = True
                        self.event(f"{task.id} done: {reason}")
                    else:
                        self.stop(task, reason)
                self.evals[task.id] = (status, reason)
                continue
            st = self.state["tasks"][task.id]
            self.evals[task.id] = (st["status"], st.get("reason", ""))
        self.save()

    def light(self) -> None:
        self.apply_requests()
        self.reconcile()
        self.launch_ready()
        self.save()

    def panes(self) -> list[Pane]:
        try:
            return self.tmux.panes(self.queue.session)
        except TmuxError as exc:
            self.event(f"tmux: {exc}")
            return []

    def reconcile(self) -> None:
        """Match state to live panes; a running task whose agent left gets verified at once."""
        panes = self.panes()
        by_id = {p.id: p for p in panes}
        self.control = next((p.id for p in panes if p.task == CONTROL), None)
        for task in self.queue.tasks:
            st = self.state["tasks"].get(task.id)
            if not st or not st.get("pane"):
                continue
            pane = by_id.get(st["pane"])
            alive = pane is not None and pane.task == task.id
            if st["status"] == "running":
                info = self.store.read_json(self.store.file("exit", task.id))
                if info is not None or not alive:
                    st.update(status="exited", exit_code=(info or {}).get("code"))
                    if not alive:
                        st["pane"] = None
                    self.verify_exit(task)
                    self.evals[task.id] = (st["status"], st.get("reason", ""))
            elif not alive:
                st["pane"] = None
            if (st["status"] == "stopped" and st.get("pane") and not st.get("parked")
                    and self.store.file("exit", task.id).exists()):
                self.park(task, st)

    def park(self, task: Task, st: dict) -> None:
        """The agent of a stopped task has left: its pane moves to its own window, the slot frees."""
        try:
            self.tmux.park(st["pane"], f"{task.id} stopped")
        except TmuxError as exc:
            self.event(f"{task.id}: could not move the stopped pane aside: {exc}")
            return
        st["parked"] = True
        self.tmux.layout(self.queue.session, self.control)
        self.event(f"{task.id}: stopped pane {st['pane']} moved to window '{task.id} stopped'; its slot is free")

    def occupied(self) -> int:
        return sum(1 for st in self.state["tasks"].values() if st.get("pane") and not st.get("parked"))

    def launch_ready(self) -> None:
        free = self.queue.panes - self.occupied()
        for task in self.queue.tasks:
            if free <= 0:
                return
            if self.status_of(task.id) not in ("pending",):
                continue
            status, _ = self.evals.get(task.id, ("pending", ""))
            agent = self.agent_for(task)
            if status == "needs-agent" and agent:
                status = "ready"
            if status != "ready" or not agent:
                continue
            if self.launch(task, agent):
                free -= 1

    def question(self) -> Task | None:
        """First task that only waits for the owner's choice of agent."""
        for task in self.queue.tasks:
            if (self.status_of(task.id) == "pending" and self.evals.get(task.id, ("",))[0] == "needs-agent"
                    and not self.agent_for(task)):
                return task
        return None

    def ask(self, force: bool = False) -> None:
        task = self.question()
        if task is None or (task.id in self.asked and not force):
            return
        self.asked.add(task.id)
        options = "  ".join(f"{i}) {name}" for i, name in enumerate(self.queue.agents, 1))
        text = (f"QUESTION: which agent runs {task.id} {task.title}? {options} "
                f"- type a number or a name (or '<task id> <agent>' for another task)")
        self.store.log(text)
        if self.out:
            self.out(text)

    def answer(self, task_id: str, agent: str) -> str:
        if not any(t.id == task_id for t in self.queue.tasks):
            return f"no task {task_id} in the queue"
        if agent not in self.queue.agents:
            return f"unknown agent {agent!r}; the queue defines {', '.join(self.queue.agents)}"
        if self.status_of(task_id) != "pending":
            return f"{task_id} is {self.status_of(task_id)}; the choice is not needed"
        self.st(task_id)["choice"] = agent
        self.event(f"{task_id}: agent {agent} chosen")
        return ""

    def reset(self, task_id: str) -> str:
        st = self.state["tasks"].get(task_id)
        if st is None:
            return ""
        if st.get("status") in ("running", "exited") and st.get("pane"):
            return f"{task_id} still has a live agent pane {st['pane']}; close it first"
        if st.get("pane"):
            self.tmux.kill_pane(st["pane"])
        del self.state["tasks"][task_id]
        self.evals.pop(task_id, None)
        self.asked.discard(task_id)
        for kind in ("launch", "exit", "verdict"):
            self.store.file(kind, task_id).unlink(missing_ok=True)
        self.dirty = True
        self.event(f"{task_id} reset by the owner")
        return ""

    def apply_requests(self) -> None:
        for kind, handler in (("answers", self._answer_file), ("resets", self._reset_file)):
            folder = self.store.root / kind
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.json")):
                data = self.store.read_json(path) or {}
                path.unlink(missing_ok=True)
                error = handler(data)
                if error:
                    self.event(error)

    def _answer_file(self, data: dict) -> str:
        return self.answer(str(data.get("task", "")), str(data.get("agent", "")))

    def _reset_file(self, data: dict) -> str:
        task_id = str(data.get("task", ""))
        if not any(t.id == task_id for t in self.queue.tasks):
            return f"reset: no task {task_id} in the queue"
        return self.reset(task_id)

    # ---- launching
    def ensure_session(self, own_pane: str | None = None) -> None:
        """Make sure the session exists and has a control pane at the bottom."""
        panes = self.panes()
        if own_pane and any(p.id == own_pane for p in panes):
            self.tmux.set_option(own_pane, TASK_OPTION, CONTROL)
            self.tmux.set_option(own_pane, LABEL_OPTION, "task-panes control")
            self.control = own_pane
            return
        viewer = [self.python, self.bin_path, "_log", "--state-dir", str(self.store.root)]
        if not self.tmux.has_session(self.queue.session):
            self.control = self.tmux.new_session(self.queue.session, viewer, str(self.queue.dir))
            return
        self.control = next((p.id for p in panes if p.task == CONTROL), None)
        if self.control is None and panes:
            self.control = self.tmux.split(panes[-1].id, viewer, str(self.queue.dir), above=False)
            self.tmux.set_option(self.control, TASK_OPTION, CONTROL)
            self.tmux.set_option(self.control, LABEL_OPTION, "task-panes control (log)")

    def launch(self, task: Task, agent: str) -> bool:
        """Prepare the workdir and open the agent pane; False when the task did not start."""
        paths = self.queue.paths(task)
        session_id = str(uuid.uuid4())
        exists = paths.worktree.exists()
        rule = self.queue.on_existing_worktree(task)
        if exists and rule == "stop":
            self.stop(task, f"worktree already exists: {paths.worktree}")
            return False
        if not (exists and rule == "resume"):
            if "prepare" in self.queue.commands:
                r = self.command("prepare", task, session_id)
                if r.code != 0:
                    self.stop(task, f"prepare failed (exit {r.code}): {r.reason}")
                    return False
            elif not exists:
                make_private_dirs(paths.worktree)
        if not paths.worktree.is_dir():
            self.stop(task, f"workdir {paths.worktree} does not exist after prepare")
            return False
        argv = self.queue.build_argv(task, agent, session_id)
        spec = self.queue.sandbox_for(task, agent, session_id)
        if spec.mode == "bwrap":
            plan = tp_sandbox.plan(spec, self.queue.agents[agent].writable, paths.worktree,
                                   sockets=[tmux_socket_path(self.tmux.socket)])
            for path in plan.create:
                make_private_dirs(path)
            argv = plan.prefix + argv
        env = agent_env(self.queue)
        env.update(self.task_env(task, session_id))
        record = {"id": task.id, "title": task.title, "agent": agent, "session_id": session_id, "argv": argv,
                  "cwd": str(paths.worktree), "env": env, "sandbox": spec.mode}
        for kind in ("exit", "verdict"):
            self.store.file(kind, task.id).unlink(missing_ok=True)
        self.store.write_json(self.store.file("launch", task.id), record)
        pane_argv = [self.python, self.bin_path, "_pane", "--state-dir", str(self.store.root), "--task", task.id]
        try:
            self.ensure_session(self.control)
            pane = self.tmux.split(self.control, pane_argv, str(paths.worktree))
            self.tmux.set_option(pane, TASK_OPTION, task.id)
            self.tmux.set_option(pane, LABEL_OPTION, f"{task.id} [{agent}] {task.title}"[:150])
            self.tmux.layout(self.queue.session, self.control)
        except TmuxError as exc:
            self.evals[task.id] = ("error", f"could not open a pane: {exc}")
            self.event(f"{task.id}: could not open a pane: {exc}")
            return False
        self.st(task.id).update(status="running", pane=pane, agent=agent, session_id=session_id,
                                started=self.clock(), reason=f"running in pane {pane}", exit_code=None,
                                parked=False)
        self.evals[task.id] = ("running", f"running in pane {pane}")
        self.event(f"{task.id} started with {agent} in pane {pane}, session id {session_id}")
        return True

    # ---- reporting
    def rows(self) -> list[dict]:
        rows = []
        for task in self.queue.tasks:
            st = self.state["tasks"].get(task.id, {})
            status, reason = self.evals.get(task.id, (st.get("status", "pending"), st.get("reason", "")))
            rows.append({"id": task.id, "title": task.title, "status": status, "reason": reason,
                         "agent": st.get("agent") or self.agent_for(task) or "", "pane": st.get("pane") or ""})
        return rows

    def would_start(self) -> list[str]:
        free = self.queue.panes - self.occupied()
        ready = [r["id"] for r in self.rows() if r["status"] in ("ready", "needs-agent")]
        return ready[:max(free, 0)]

    def all_done(self) -> bool:
        return all(self.status_of(t.id) == "done" for t in self.queue.tasks)


def table(rows: list[dict]) -> str:
    head = ("ID", "STATUS", "AGENT", "PANE", "TITLE", "REASON")
    keys = ("id", "status", "agent", "pane", "title", "reason")
    cells = [head] + [tuple((r[k] if k != "title" else _cut(r[k], 48)) for k in keys) for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(len(head) - 1)]
    lines = []
    for c in cells:
        lines.append("  ".join(c[i].ljust(widths[i]) for i in range(len(head) - 1)) + "  " + c[-1])
    return "\n".join(line.rstrip() for line in lines)


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "~"


def serve(engine: Engine, stdin=None, stop_flag=None) -> int:
    """Control loop: heavy cycle every poll_seconds, light every few seconds, owner input between."""
    stop = {"now": False}

    def handler(signum, frame):
        stop["now"] = True
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGHUP, handler)
    reading = stdin is not None
    heavy_due = 0.0
    engine.event(f"runner started for {engine.queue.path} ({engine.queue.panes} panes); "
                 "type 'h' for help")
    while not stop["now"] and not (stop_flag and stop_flag()):
        if engine.clock() >= heavy_due or engine.dirty:
            engine.dirty = False
            engine.heavy()
            heavy_due = engine.clock() + engine.queue.poll_seconds
        engine.light()
        if engine.dirty:
            continue
        engine.ask()
        if engine.all_done():
            engine.event("all tasks are done; the runner exits")
            return 0
        wait = min(LIGHT_SECONDS, engine.queue.poll_seconds)
        if not reading:
            time.sleep(wait)
            continue
        try:
            ready, _, _ = select.select([stdin], [], [], wait)
        except (OSError, ValueError):
            reading = False
            continue
        if not ready:
            continue
        line = stdin.readline()
        if line == "":
            reading = False
            continue
        if handle_input(engine, line.strip()) == "quit":
            break
    engine.event("runner stopped; agent panes keep running and are picked up by the next runner")
    return 0


HELP = ("commands: <number>|<agent> answers the current question; '<task> <agent>' chooses for a task; "
        "s - status; reset <task> - make a stopped task startable again; q - stop the runner "
        "(agent panes keep running)")


def handle_input(engine: Engine, line: str) -> str:
    say = engine.out or print
    words = line.split()
    agents = list(engine.queue.agents)
    if not words:
        engine.ask(force=True)
        return ""
    if words[0] in ("q", "quit", "exit"):
        return "quit"
    if words[0] in ("h", "help", "?"):
        say(HELP)
    elif words[0] in ("s", "status"):
        say(table(engine.rows()))
    elif words[0] == "reset" and len(words) == 2:
        error = engine.reset(words[1])
        if error:
            say(error)
    elif len(words) == 1:
        task = engine.question()
        choice = words[0]
        if choice.isdigit() and 1 <= int(choice) <= len(agents):
            choice = agents[int(choice) - 1]
        if task is None:
            say("there is no open question; " + HELP)
        else:
            error = engine.answer(task.id, choice)
            say(error) if error else None
    elif len(words) == 2:
        choice = words[1]
        if choice.isdigit() and 1 <= int(choice) <= len(agents):
            choice = agents[int(choice) - 1]
        error = engine.answer(words[0], choice)
        if error:
            say(error)
    else:
        say(HELP)
    engine.save()
    return ""


def _default_sigint() -> None:
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def pane_main(root: Path, task_id: str, stdin=sys.stdin) -> int:
    """Body of an agent pane: run the agent, report its exit, then show the runner's verdict."""
    store = Store(root)
    launch = store.read_json(store.file("launch", task_id))
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if not launch:
        print(f"task-panes: no launch record for {task_id} in {root}")
        code = None
    else:
        print(f"== {task_id} {launch.get('title', '')}\n   agent {launch['agent']}, session id "
              f"{launch['session_id']}\n   workdir {launch['cwd']}, sandbox {launch.get('sandbox')}\n", flush=True)
        env = {k: os.environ[k] for k in PANE_ENV if k in os.environ}
        env.update(launch.get("env", {}))
        try:
            proc = subprocess.Popen(launch["argv"], cwd=launch["cwd"], env=env, preexec_fn=_default_sigint)
            code = proc.wait()
        except OSError as exc:
            print(f"task-panes: cannot start the agent: {exc}")
            code = 127
    store.write_json(store.file("exit", task_id), {"code": code, "at": time.time()})
    print(f"\n== {task_id}: agent exited (code {code}); waiting for the runner's completion check...", flush=True)
    while True:
        verdict = store.read_json(store.file("verdict", task_id))
        if verdict and verdict.get("status") == "stopped":
            print(f"== {task_id} STOPPED: {verdict.get('reason')}\n"
                  "   It will not restart by itself. Press Enter to close this pane (the task stays stopped);\n"
                  "   `task-panes reset <queue> <task>` makes it startable again.", flush=True)
            try:
                stdin.readline()
            except (OSError, ValueError):
                time.sleep(3600 * 24 * 365)
            return 0
        time.sleep(1)


def log_main(root: Path) -> int:
    """Control pane of a runner that lives outside tmux: follow its log."""
    path = Path(root) / "runner.log"
    print("task-panes: the runner runs outside this session; this pane shows its log.\n"
          "Answer agent questions with `task-panes answer <queue> <task> <agent>`.", flush=True)
    offset = 0
    while True:
        try:
            with open(path, encoding="utf-8") as fh:
                fh.seek(offset)
                chunk = fh.read()
                offset = fh.tell()
            if chunk:
                print(chunk, end="", flush=True)
        except FileNotFoundError:
            pass
        time.sleep(1)
