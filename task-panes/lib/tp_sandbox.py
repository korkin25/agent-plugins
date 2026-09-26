"""Build the bubblewrap command line that confines one agent to its task."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Personal data an agent never needs: browser profiles, mail, keyrings, password databases.
DEFAULT_HIDDEN = [
    "~/.mozilla", "~/snap/firefox", "~/.config/google-chrome", "~/.config/chromium",
    "~/.config/BraveSoftware", "~/.config/microsoft-edge", "~/.config/vivaldi", "~/.config/opera",
    "~/.cache/google-chrome", "~/.cache/chromium", "~/.cache/mozilla", "~/.cache/BraveSoftware",
    "~/.thunderbird", "~/.local/share/evolution", "~/.config/evolution", "~/.local/share/akonadi",
    "~/.local/share/kmail2", "~/Mail", "~/.mail",
    "~/.local/share/keyrings", "~/.local/share/kwalletd", "~/.gnupg", "~/.password-store",
    "~/.config/keepassxc", "~/.cache/keepassxc", "~/*.kdbx", "~/Documents/*.kdbx",
]

# Daemon sockets that run commands outside the sandbox for any member of their group.
DEFAULT_HIDDEN_SYSTEM = [
    "/run/docker.sock", "/var/run/docker.sock", "/run/podman/podman.sock",
    "/var/snap/lxd/common/lxd/unix.socket", "/var/lib/lxd/unix.socket", "/var/lib/incus/unix.socket",
    "/run/incus/unix.socket", "/run/libvirt/libvirt-sock", "/var/run/libvirt/libvirt-sock",
]

# Variables that point outside the sandbox: the session bus and the tmux server.
UNSET_ENV = ["DBUS_SESSION_BUS_ADDRESS", "TMUX", "TMUX_PANE"]
TIOCSTI_SYSCTL = "/proc/sys/dev/tty/legacy_tiocsti"

# State each agent CLI writes while it runs; bound writable only where it already exists.
AGENT_STATE = {
    "claude": ["~/.claude", "~/.claude.json", "~/.claude.json.backup", "~/.cache/claude",
               "~/.cache/claude-cli-nodejs", "~/.local/state/claude", "~/.local/share/claude"],
    "codex": ["~/.codex", "~/.cache/codex-runtimes", "~/.local/state/codex",
              "~/.local/state/openai-codex"],
}


# $HOME is an empty tmpfs; only these come back read-only (where they exist), found by tracing
# git, ssh, glab and python3 and by where claude and codex install. No keys or tokens here.
DEFAULT_HOME_ALLOW = [
    "~/.gitconfig", "~/.config/git",
    "~/.ssh/config", "~/.ssh/known_hosts", "~/.ssh/known_hosts2",
    "~/.local/bin", "~/.local/lib",
    "~/.nvm", "~/.volta", "~/.npm-global", "~/.bun/bin", "~/.local/share/pnpm",
]


@dataclass
class SandboxSpec:
    mode: str = "bwrap"
    writable: list[str] = field(default_factory=list)
    readonly: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    hide_defaults: bool = True
    private_tmp: bool = True
    tmpdir: str = ""
    extra_args: list[str] = field(default_factory=list)
    home_allow: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """Resolved paths plus the argv prefix; `create` lists directories to make first."""
    prefix: list[str]
    create: list[Path]
    writable: list[Path]
    readonly: list[Path]
    hidden: list[Path]
    tmpdir: Path | None
    home_allow: list[Path] = field(default_factory=list)


def expand(path: str, home: str) -> Path:
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    return Path(os.path.normpath(path))


def _hidden(patterns: list[str], home: str) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        path = str(expand(pattern, home))
        matches = glob.glob(path) if any(ch in path for ch in "*?[") else [path]
        out.extend(Path(m) for m in matches if os.path.lexists(m))
    return out


def _depth(path: Path) -> int:
    return len(path.parts)


def runtime_dir(env) -> str:
    return env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def tiocsti_allowed(path: str = TIOCSTI_SYSCTL) -> bool:
    """True unless the kernel refuses TIOCSTI to unprivileged processes (Linux 6.2+ sysctl)."""
    try:
        return Path(path).read_text().strip() != "0"
    except OSError:
        return True


def plan(spec: SandboxSpec, agent_state: list[str], cwd: Path, home: str | None = None,
         bwrap: str = "bwrap", sockets: list[str] | None = None, env=None,
         tiocsti: bool | None = None) -> Plan:
    """$HOME starts empty: agent state and queue paths bind writable, the allow list read-only.

    `sockets` are control sockets (the tmux server) whose directories the agent must not reach."""
    home = home or os.path.expanduser("~")
    env = os.environ if env is None else env
    create: list[Path] = []
    writable: list[Path] = []
    for raw in spec.writable:
        path = expand(raw, home)
        if not os.path.lexists(path):
            create.append(path)
        writable.append(path)
    for raw in agent_state:
        path = expand(raw, home)
        if os.path.lexists(path):
            writable.append(path)
    if not os.path.lexists(cwd):
        create.append(cwd)
    if cwd not in writable:
        writable.append(cwd)
    tmpdir = expand(spec.tmpdir, home) if spec.tmpdir else None
    if tmpdir is not None and tmpdir not in writable:
        writable.append(tmpdir)
        if not os.path.lexists(tmpdir):
            create.append(tmpdir)
    readonly = [expand(p, home) for p in spec.readonly]
    readonly = [p for p in readonly if os.path.lexists(p)]
    hidden = _hidden((DEFAULT_HIDDEN + DEFAULT_HIDDEN_SYSTEM if spec.hide_defaults else []) + spec.hidden, home)
    # bwrap mounts over the target of a symlink, never through it (/var/run -> /run).
    hidden = [Path(p) for p in dict.fromkeys(os.path.realpath(p) for p in hidden) if os.path.exists(p)]
    writable = sorted(set(writable), key=_depth)
    args = [bwrap, "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--ro-bind", "/", "/",
            "--dev-bind", "/dev", "/dev", "--tmpfs", "/dev/shm", "--proc", "/proc"]
    if tiocsti if tiocsti is not None else tiocsti_allowed():
        args.append("--new-session")
    # The runtime dir holds the session bus, systemd --user and gpg-agent: each runs commands
    # outside the sandbox, so it is replaced by an empty tmpfs; only the ssh-agent socket returns.
    runtime = runtime_dir(env)
    covered = (["/tmp"] if spec.private_tmp else []) + ([runtime] if os.path.isdir(runtime) else [])
    for root in covered:
        args += ["--tmpfs", root]
    home_path = Path(home)
    private_home = home_path.is_dir()
    if private_home:
        args += ["--tmpfs", home]
    # The ssh-agent socket returns from an emptied root, never from inside a hidden path.
    sock = env.get("SSH_AUTH_SOCK", "")
    roots = covered + ([home] if private_home else [])
    if sock and os.path.exists(sock) and any(_under(sock, r) for r in roots) \
            and not any(_under(sock, str(h)) for h in hidden):
        args += ["--ro-bind", sock, sock]
    allow = [expand(p, home) for p in DEFAULT_HOME_ALLOW + spec.home_allow]
    allow = [p for p in dict.fromkeys(allow) if os.path.exists(p) and p not in writable]
    binds = [(p, "--bind") for p in writable if p.exists() or p in create]
    binds += [(p, "--ro-bind") for p in readonly + allow]
    for path, flag in sorted(binds, key=lambda b: (_depth(b[0]), b[1] == "--ro-bind")):
        args += [flag, str(path), str(path)]
    bound = [str(p) for p, _ in binds]
    emptied = covered + ([home, os.path.realpath(home)] if private_home else [])

    def gone(path: str) -> bool:
        """True when an emptied root already removed path and no bind brings it back."""
        return any(_under(path, r) for r in emptied) and not any(_under(path, b) for b in bound)
    for path in sorted(hidden, key=_depth):
        if gone(str(path)):
            continue
        args += ["--tmpfs", str(path)] if path.is_dir() and not path.is_symlink() else \
                ["--ro-bind", "/dev/null", str(path)]
    tmux_env = env.get("TMUX", "").split(",")[0]
    for socket in dict.fromkeys([s for s in (sockets or []) + [tmux_env] if s]):
        parent = os.path.dirname(socket)
        if os.path.isdir(parent) and not gone(parent):
            args += ["--tmpfs", parent]
    for name in UNSET_ENV:
        args += ["--unsetenv", name]
    if tmpdir is not None:
        args += ["--setenv", "TMPDIR", str(tmpdir)]
    args += list(spec.extra_args) + ["--chdir", str(cwd), "--"]
    return Plan(args, create, writable, readonly, hidden, tmpdir, allow)


def _under(path: str, root: str) -> bool:
    return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)


def probe(bwrap: str = "bwrap") -> str | None:
    """None when bwrap can start a sandbox here, otherwise the reason it cannot."""
    exe = shutil.which(bwrap)
    if not exe:
        return f"{bwrap} is not installed"
    try:
        proc = subprocess.run([exe, "--unshare-pid", "--unshare-ipc", "--ro-bind", "/", "/", "--dev-bind",
                               "/dev", "/dev", "--tmpfs", "/dev/shm", "--proc", "/proc", "--tmpfs", "/tmp",
                               "--", "true"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{bwrap} failed to start: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return f"{bwrap} cannot create a sandbox: {detail[-1] if detail else 'exit ' + str(proc.returncode)}"
    return None
