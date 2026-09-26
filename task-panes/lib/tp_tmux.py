"""Thin wrapper over the tmux CLI: one session, a tasks window of stacked panes, stopped ones apart."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass

TASK_OPTION = "@task_panes_task"
LABEL_OPTION = "@task_panes_label"
CONTROL = "control"
BORDER_FORMAT = " #{?" + LABEL_OPTION + ",#{" + LABEL_OPTION + "},#{pane_title}} "


def socket_path(socket: str | None, env=None) -> str:
    """Where the tmux server for `-L socket` (or the default one) listens, as tmux resolves it."""
    env = os.environ if env is None else env
    if not socket and env.get("TMUX"):
        return env["TMUX"].split(",")[0]
    base = env.get("TMUX_TMPDIR") or "/tmp"
    return os.path.join(base, f"tmux-{os.getuid()}", socket or "default")


class TmuxError(Exception):
    """A tmux command failed; the message carries tmux's own explanation."""


@dataclass
class Pane:
    id: str
    task: str
    dead: bool


class Tmux:
    def __init__(self, socket: str | None = None, exe: str = "tmux"):
        self.socket = socket
        self.exe = exe

    def available(self) -> bool:
        return shutil.which(self.exe) is not None

    def _run(self, *args: str, check: bool = True) -> str:
        argv = [self.exe] + (["-L", self.socket] if self.socket else []) + list(args)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TmuxError(f"tmux did not run: {exc}") from None
        if check and proc.returncode != 0:
            raise TmuxError(f"tmux {args[0]}: {(proc.stderr or proc.stdout).strip() or proc.returncode}")
        return proc.stdout

    def has_session(self, session: str) -> bool:
        argv = [self.exe] + (["-L", self.socket] if self.socket else []) + ["has-session", "-t", f"={session}"]
        try:
            return subprocess.run(argv, capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def new_session(self, session: str, argv: list[str], cwd: str) -> str:
        """Create the detached session whose only pane is the control pane; return its id."""
        pane = self._run("new-session", "-d", "-s", session, "-n", "tasks", "-x", "200", "-y", "50",
                         "-c", cwd, "-P", "-F", "#{pane_id}", shlex.join(argv)).strip()
        self._run("set-option", "-w", "-t", f"={session}:tasks", "remain-on-exit", "off")
        self._run("set-window-option", "-t", f"={session}:tasks", "pane-border-status", "top")
        self._run("set-window-option", "-t", f"={session}:tasks", "pane-border-format", BORDER_FORMAT)
        self.set_option(pane, TASK_OPTION, CONTROL)
        self.set_option(pane, LABEL_OPTION, "task-panes control")
        return pane

    def respawn(self, pane: str, argv: list[str], cwd: str) -> None:
        self._run("respawn-pane", "-k", "-t", pane, "-c", cwd, shlex.join(argv))

    def split(self, target: str | None, argv: list[str], cwd: str, above: bool = True) -> str:
        """Open a pane above target (the control pane stays at the bottom); return its id."""
        where = ["-t", target] if target else []
        return self._run("split-window", "-v", *(["-b"] if above else []), "-d", *where, "-c", cwd,
                         "-P", "-F", "#{pane_id}", shlex.join(argv)).strip()

    def socket_path(self) -> str:
        out = self._run("list-sessions", "-F", "#{socket_path}", check=False).splitlines()
        return out[0].strip() if out else ""

    def set_option(self, pane: str, key: str, value: str) -> None:
        self._run("set-option", "-p", "-t", pane, key, value)

    def panes(self, session: str) -> list[Pane]:
        if not self.has_session(session):
            return []
        fmt = "#{pane_id}\t#{" + TASK_OPTION + "}\t#{pane_dead}"
        out = self._run("list-panes", "-s", "-t", f"={session}", "-F", fmt, check=False)
        panes = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("%"):
                panes.append(Pane(parts[0], parts[1], parts[2] == "1"))
        return panes

    def park(self, pane: str, name: str) -> None:
        """Move a pane out of the tasks window into a window of its own, without switching to it."""
        window = self._run("break-pane", "-d", "-s", pane, "-n", name, "-P", "-F", "#{window_id}").strip()
        self._run("set-window-option", "-t", window, "pane-border-status", "top", check=False)
        self._run("set-window-option", "-t", window, "pane-border-format", BORDER_FORMAT, check=False)

    def kill_pane(self, pane: str) -> None:
        self._run("kill-pane", "-t", pane, check=False)

    def kill_session(self, session: str) -> None:
        self._run("kill-session", "-t", f"={session}", check=False)

    def layout(self, session: str, control: str | None, control_rows: int = 8) -> None:
        self._run("select-layout", "-t", f"={session}:tasks", "even-vertical", check=False)
        if control:
            self._run("resize-pane", "-t", control, "-y", str(control_rows), check=False)

    def attach_argv(self, session: str) -> list[str]:
        return [self.exe] + (["-L", self.socket] if self.socket else []) + ["attach", "-t", f"={session}"]
