"""Queue file loading, validation and placeholder rendering for task-panes."""
from __future__ import annotations

import hashlib
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tp_sandbox import AGENT_STATE, SandboxSpec


class QueueError(Exception):
    """A queue file that cannot be used, with a message meant for the user."""


TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}|[{}]")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SESSION = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_AGENTS = {
    "claude": {"command": ["claude", "--session-id", "{session_id}", "{prompt}"]},
    "codex": {"command": ["codex", "{prompt}"]},
}
DEFAULT_PROMPT = "Work on task {id}: {title}"
TOP_KEYS = {
    "session", "panes", "poll_seconds", "command_timeout", "agent", "tmux_socket", "state_dir",
    "worktree_exists", "slug", "worktree", "branch", "prompt", "env", "vars", "commands",
    "agents", "sandbox", "tasks", "pass_env",
}
WORKTREE_EXISTS = ("prepare", "stop", "resume")
SANDBOX_KEYS = {"mode", "writable", "readonly", "hidden", "hide_defaults", "private_tmp", "tmpdir",
                "extra_args", "home_allow"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMMAND_KEYS = {"refresh", "done", "dependencies", "dependency_done", "prepare"}
AGENT_KEYS = {"command", "vars", "prompt_prefix", "writable"}
TASK_RESERVED = {"id", "title", "agent", "depends_on", "slug", "worktree", "branch", "extra_prompt",
                 "worktree_exists"}
COMPUTED = ("id", "id_lower", "title", "slug", "worktree", "branch", "session_id", "agent",
            "queue_dir", "session")


def render(template: str, ctx: dict) -> str:
    """Replace {name} from ctx; {{ and }} are literal braces; unknown names fail."""
    def sub(match: re.Match) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1)
        if name is None:
            raise QueueError(f"unpaired brace in template {template[:60]!r}; write {{{{ or }}}} for a literal one")
        if name not in ctx:
            raise QueueError(f"unknown placeholder {{{name}}} in template {template[:60]!r}")
        return str(ctx[name])
    return TOKEN.sub(sub, template)


@dataclass
class Agent:
    name: str
    command: list[str]
    vars: dict[str, str] = field(default_factory=dict)
    prompt_prefix: str = ""
    writable: list[str] = field(default_factory=list)


@dataclass
class Task:
    id: str
    title: str = ""
    agent: str | None = None
    depends_on: list[str] = field(default_factory=list)
    slug: str | None = None
    worktree: str | None = None
    branch: str | None = None
    extra_prompt: str = ""
    worktree_exists: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Paths:
    slug: str
    worktree: Path
    branch: str


@dataclass
class Queue:
    path: Path
    session: str
    panes: int = 2
    poll_seconds: float = 30.0
    command_timeout: float = 120.0
    agent: str | None = None
    tmux_socket: str | None = None
    state_dir: Path | None = None
    worktree_exists: str = "prepare"
    slug: str = "{id_lower}"
    worktree: str = "{queue_dir}/{slug}"
    branch: str = "{slug}"
    prompt: str = DEFAULT_PROMPT
    env: dict[str, str] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)
    commands: dict[str, str] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    sandbox: SandboxSpec = field(default_factory=SandboxSpec)
    tasks: list[Task] = field(default_factory=list)
    pass_env: list[str] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return self.path.parent

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise QueueError(f"no task {task_id} in {self.path}")

    def resolve_agent(self, task: Task) -> str | None:
        """The agent fixed by the task, the queue, or the only configured one; else None."""
        if task.agent:
            return task.agent
        if self.agent:
            return self.agent
        if len(self.agents) == 1:
            return next(iter(self.agents))
        return None

    def context(self, task: Task, agent: str | None = None, session_id: str = "") -> dict:
        ctx: dict = dict(self.vars)
        if agent and agent in self.agents:
            ctx.update(self.agents[agent].vars)
        ctx.update(task.fields)
        ctx.update(id=task.id, id_lower=task.id.lower(), title=task.title, session_id=session_id,
                   agent=agent or "", queue_dir=str(self.dir), session=self.session)
        ctx["slug"] = render(task.slug or self.slug, ctx)
        worktree = Path(os.path.expanduser(render(task.worktree or self.worktree, ctx)))
        ctx["worktree"] = str(worktree if worktree.is_absolute() else self.dir / worktree)
        ctx["branch"] = render(task.branch or self.branch, ctx)
        return ctx

    def on_existing_worktree(self, task: Task) -> str:
        """prepare: run prepare anyway; stop: mark stopped; resume: skip prepare, start there."""
        return task.worktree_exists or self.worktree_exists

    def sandbox_for(self, task: Task, agent: str, session_id: str) -> SandboxSpec:
        ctx = self.context(task, agent, session_id)
        spec = self.sandbox
        return SandboxSpec(spec.mode, [render(p, ctx) for p in spec.writable],
                           [render(p, ctx) for p in spec.readonly], [render(p, ctx) for p in spec.hidden],
                           spec.hide_defaults, spec.private_tmp, render(spec.tmpdir, ctx),
                           [render(a, ctx) for a in spec.extra_args], [render(p, ctx) for p in spec.home_allow])

    def paths(self, task: Task) -> Paths:
        ctx = self.context(task)
        return Paths(ctx["slug"], Path(ctx["worktree"]), ctx["branch"])

    def build_prompt(self, task: Task, agent: str, session_id: str) -> str:
        ctx = self.context(task, agent, session_id)
        parts = [render(self.agents[agent].prompt_prefix, ctx)] if self.agents[agent].prompt_prefix else []
        parts.append(render(self.prompt, ctx))
        if task.extra_prompt:
            parts.append(render(task.extra_prompt, ctx))
        return "\n\n".join(p.strip() for p in parts if p.strip())

    def build_argv(self, task: Task, agent: str, session_id: str) -> list[str]:
        ctx = self.context(task, agent, session_id)
        ctx["prompt"] = self.build_prompt(task, agent, session_id)
        return [render(part, ctx) for part in self.agents[agent].command]


def default_state_dir(path: Path, session: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:10]
    return Path(base) / "task-panes" / f"{session}-{digest}"


def _str(value, where: str) -> str:
    if not isinstance(value, str):
        raise QueueError(f"{where} must be a string")
    return value


def _str_map(value, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise QueueError(f"[{where}] must be a table")
    out = {}
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise QueueError(f"{where}.{key} must be a string or a number")
        out[key] = str(item)
    return out


def _str_list(value, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise QueueError(f"{where} must be a list of strings")
    return list(value)


def _sandbox(raw) -> SandboxSpec:
    if raw is None:
        return SandboxSpec()
    if not isinstance(raw, dict):
        raise QueueError("[sandbox] must be a table")
    unknown = set(raw) - SANDBOX_KEYS
    if unknown:
        raise QueueError(f"[sandbox]: unknown keys {sorted(unknown)}; allowed: {sorted(SANDBOX_KEYS)}")
    mode = raw.get("mode", "bwrap")
    if mode not in ("bwrap", "none"):
        raise QueueError('sandbox.mode must be "bwrap" or "none"')
    flags = {}
    for key in ("hide_defaults", "private_tmp"):
        value = raw.get(key, True)
        if not isinstance(value, bool):
            raise QueueError(f"sandbox.{key} must be true or false")
        flags[key] = value
    lists = {k: _str_list(raw.get(k, []), f"sandbox.{k}")
             for k in ("writable", "readonly", "hidden", "extra_args", "home_allow")}
    return SandboxSpec(mode, lists["writable"], lists["readonly"], lists["hidden"], flags["hide_defaults"],
                       flags["private_tmp"], _str(raw.get("tmpdir", ""), "sandbox.tmpdir"), lists["extra_args"],
                       lists["home_allow"])


def _agents(raw) -> dict[str, Agent]:
    if raw is None:
        raw = DEFAULT_AGENTS
    if not isinstance(raw, dict) or not raw:
        raise QueueError("[agents] must be a table with at least one agent")
    agents = {}
    for name, spec in raw.items():
        if not NAME.match(name) or not isinstance(spec, dict):
            raise QueueError(f"agents.{name} must be a table with a simple name")
        unknown = set(spec) - AGENT_KEYS
        if unknown:
            raise QueueError(f"agents.{name}: unknown keys {sorted(unknown)}")
        command = spec.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            raise QueueError(f"agents.{name}.command must be a non-empty list of strings (argv)")
        writable = spec.get("writable")
        if writable is None:
            writable = AGENT_STATE.get(os.path.basename(command[0]), [])
        agents[name] = Agent(name, list(command), _str_map(spec.get("vars"), f"agents.{name}.vars"),
                             _str(spec.get("prompt_prefix", ""), f"agents.{name}.prompt_prefix"),
                             _str_list(writable, f"agents.{name}.writable"))
    return agents


def _task(raw, index: int) -> Task:
    if isinstance(raw, str):
        raw = {"id": raw}
    if not isinstance(raw, dict):
        raise QueueError(f"tasks[{index}] must be a string id or a table")
    task_id = raw.get("id")
    if not isinstance(task_id, str) or not NAME.match(task_id):
        raise QueueError(f"tasks[{index}].id must be letters, digits, '.', '_' or '-'")
    depends = raw.get("depends_on", [])
    if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
        raise QueueError(f"{task_id}: depends_on must be a list of task ids")
    fields = {}
    for key, value in raw.items():
        if key in TASK_RESERVED:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise QueueError(f"{task_id}: field {key} must be a string or a number")
        fields[key] = str(value)
    opt = {k: _str(raw[k], f"{task_id}.{k}")
           for k in ("agent", "slug", "worktree", "branch", "worktree_exists") if k in raw}
    if opt.get("worktree_exists", WORKTREE_EXISTS[0]) not in WORKTREE_EXISTS:
        raise QueueError(f"{task_id}.worktree_exists must be one of {list(WORKTREE_EXISTS)}")
    return Task(task_id, _str(raw.get("title", ""), f"{task_id}.title"), opt.get("agent"), list(depends),
                opt.get("slug"), opt.get("worktree"), opt.get("branch"),
                _str(raw.get("extra_prompt", ""), f"{task_id}.extra_prompt"), opt.get("worktree_exists"),
                fields)


def load(path: str | os.PathLike) -> Queue:
    """Read and validate a queue file; every problem raises QueueError."""
    path = Path(os.path.expanduser(str(path))).resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise QueueError(f"queue file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise QueueError(f"cannot read {path}: {exc}") from None
    except tomllib.TOMLDecodeError as exc:
        raise QueueError(f"{path} is not valid TOML: {exc}") from None
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise QueueError(f"unknown top-level keys {sorted(unknown)}; allowed: {sorted(TOP_KEYS)}")
    session = data.get("session")
    if not isinstance(session, str) or not SESSION.match(session):
        raise QueueError("session must name the tmux session: letters, digits, '_' or '-'")
    panes = data.get("panes", 2)
    if isinstance(panes, bool) or not isinstance(panes, int) or not 1 <= panes <= 16:
        raise QueueError("panes must be an integer from 1 to 16")
    numbers = {}
    for key, default, low in (("poll_seconds", 30.0, 0.2), ("command_timeout", 120.0, 1.0)):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < low:
            raise QueueError(f"{key} must be a number of seconds, at least {low}")
        numbers[key] = float(value)
    commands = _str_map(data.get("commands"), "commands")
    unknown = set(commands) - COMMAND_KEYS
    if unknown:
        raise QueueError(f"[commands]: unknown keys {sorted(unknown)}; allowed: {sorted(COMMAND_KEYS)}")
    if not commands.get("done"):
        raise QueueError("[commands] done is required: the runner decides completion by it, not by the agent")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise QueueError("tasks must be a non-empty list")
    tasks = [_task(raw, i) for i, raw in enumerate(raw_tasks)]
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise QueueError("task ids must be unique")
    agents = _agents(data.get("agents"))
    agent = data.get("agent")
    for who, name in [("agent", agent)] + [(f"{t.id}.agent", t.agent) for t in tasks]:
        if name is not None and name not in agents:
            raise QueueError(f"{who} = {name!r}, but [agents] defines only {sorted(agents)}")
    for task in tasks:
        if task.id in task.depends_on:
            raise QueueError(f"{task.id} depends on itself")
    state_dir = data.get("state_dir")
    if state_dir is not None:
        state_dir = Path(os.path.expanduser(_str(state_dir, "state_dir")))
        state_dir = state_dir if state_dir.is_absolute() else path.parent / state_dir
    socket = data.get("tmux_socket")
    if socket is not None and not SESSION.match(_str(socket, "tmux_socket")):
        raise QueueError("tmux_socket must be a plain socket name for tmux -L")
    pass_env = _str_list(data.get("pass_env", []), "pass_env")
    for i, name in enumerate(pass_env):
        if not ENV_NAME.match(name):
            raise QueueError(f"pass_env[{i}] is not a variable name; list names, never values")
    worktree_exists = data.get("worktree_exists", "prepare")
    if worktree_exists not in WORKTREE_EXISTS:
        raise QueueError(f"worktree_exists must be one of {list(WORKTREE_EXISTS)}")
    queue = Queue(
        path=path, session=session, panes=panes, poll_seconds=numbers["poll_seconds"],
        command_timeout=numbers["command_timeout"], agent=agent, tmux_socket=socket,
        state_dir=state_dir or default_state_dir(path, session),
        worktree_exists=worktree_exists,
        slug=_str(data.get("slug", "{id_lower}"), "slug"),
        worktree=_str(data.get("worktree", "{queue_dir}/{slug}"), "worktree"),
        branch=_str(data.get("branch", "{slug}"), "branch"),
        prompt=_str(data.get("prompt", DEFAULT_PROMPT), "prompt"),
        env=_str_map(data.get("env"), "env"), vars=_str_map(data.get("vars"), "vars"),
        commands=commands, agents=agents, sandbox=_sandbox(data.get("sandbox")), tasks=tasks,
        pass_env=pass_env)
    for task in tasks:  # render every template once so a typo fails now, not at launch
        for name in agents:
            queue.build_argv(task, name, "00000000-0000-0000-0000-000000000000")
            queue.sandbox_for(task, name, "00000000-0000-0000-0000-000000000000")
    return queue
