"""Bounded, local installed-version notices; never reload or update a plugin.

The caller must load its existing valid configuration before calling this module.
Only UUID session hashes, versions and timestamps persist. Fixed slots retain
notice history for up to 30 days under collisions; full slots fail silently.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import uuid

from router_claude_state import _directory, _linked, _safe_file

MAX_SLOTS = 256
MAX_BYTES = 4096
MAX_INPUT_BYTES = 256 * 1024
CACHE_SECONDS = 60
TTL_SECONDS = 30 * 24 * 60 * 60
MAX_NOTICES = 16
CLI_TIMEOUT = 1.0
PLUGIN_ID = "subagent-model-router@korkin25"
_VERSION = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z")


def _version(value):
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    return tuple(map(int, match.groups())) if match else None


def _client(plugin_root):
    actual = Path(plugin_root).resolve(strict=True)
    matches = []
    for client, variable, default in (("claude", "CLAUDE_CONFIG_DIR", ".claude"),
                                       ("codex", "CODEX_HOME", ".codex")):
        base = Path(os.environ.get(variable) or Path.home() / default)
        if not base.is_absolute():
            continue
        try:
            base = base.resolve(strict=True)
        except OSError:
            continue
        cache = base / "plugins/cache/korkin25/subagent-model-router"
        if actual.parent == cache and _version(actual.name):
            matches.append((client, base, cache))
    return matches[0] if len(matches) == 1 else None


def _session(event):
    # Native Codex UserPromptSubmit always includes turn_id, including root
    # prompts. Only a populated agent_id is evidence of a subagent context;
    # absent/null agent_id is the root form across supported host versions.
    if (not isinstance(event, dict) or event.get("hook_event_name") not in
            {"SessionStart", "UserPromptSubmit"} or event.get("agent_id") is not None):
        return None
    value = event.get("session_id")
    if not isinstance(value, str) or len(value) != 36:
        return None
    parsed = uuid.UUID(value)
    return str(parsed) if str(parsed) == value.lower() and parsed.version in range(1, 9) else None


def _metadata_directory(path):
    """Read-only directory walk allowing ordinary private-owner 0755 metadata."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not sticky):
                raise OSError("metadata_ancestor")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _claude_installed(base, cache, event):
    directory = fd = None
    try:
        # Registry is metadata only: do not inspect settings, credentials or sessions.
        directory = _metadata_directory(base / "plugins")
        fd = os.open("installed_plugins.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or not 0 < info.st_size <= MAX_INPUT_BYTES):
            return None
        registry = json.loads(os.read(fd, MAX_INPUT_BYTES + 1))
        entries = registry.get("plugins", {}).get(PLUGIN_ID)
        if not isinstance(entries, list) or len(entries) > 128:
            return None
        applicable = []
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            scope = entry.get("scope")
            if scope == "user":
                applicable.append(entry)
            elif scope in {"project", "local"}:
                project, cwd = entry.get("projectPath"), event.get("cwd")
                if not isinstance(project, str) or not isinstance(cwd, str):
                    return None
                project, cwd = Path(project), Path(cwd)
                if not project.is_absolute() or not cwd.is_absolute() or ".." in project.parts or ".." in cwd.parts:
                    return None
                if cwd == project or project in cwd.parents:
                    applicable.append(entry)
            else:
                return None
        if len(applicable) != 1:
            return None
        entry = applicable[0]
        version, install = entry.get("version"), entry.get("installPath")
        if not _version(version) or not isinstance(install, str):
            return None
        return version if Path(install).resolve(strict=True) == cache / version else None
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def _codex_output(binary):
    """Read at most 256 KiB in <=1 second, discard stderr, kill on overflow."""
    if not isinstance(binary, (str, os.PathLike)) or not Path(binary).is_absolute():
        return None
    process = None
    try:
        deadline = time.monotonic() + CLI_TIMEOUT
        process = subprocess.Popen([str(binary), "plugin", "list", "--marketplace", "korkin25", "--json"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return None
                chunk = os.read(process.stdout.fileno(), min(65536, MAX_INPUT_BYTES + 1 - len(output)))
                if not chunk:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or process.wait(timeout=remaining) != 0:
                        return None
                    return bytes(output)
                output.extend(chunk)
                if len(output) > MAX_INPUT_BYTES:
                    return None
    finally:
        if process is not None:
            # Also stop a child retaining stdout after its parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=0.1)
            process.stdout.close()


def _codex_installed(binary):
    output = _codex_output(binary)
    if output is None:
        return None
    data = json.loads(output)
    entries = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(entries, list) or len(entries) > 2048:
        return None
    found = [item for item in entries if isinstance(item, dict) and
             item.get("pluginId") == PLUGIN_ID and item.get("name") == "subagent-model-router"]
    if len(found) != 1:
        return None
    item = found[0]
    version = item.get("version")
    return version if item.get("installed") is True and item.get("enabled") is True and _version(version) else None


def _state_directory(config_dir):
    parent = _directory(config_dir, create=False)
    try:
        try:
            os.mkdir("update-notice", 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        child = os.open("update-notice", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        info = os.fstat(child)
        if info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o700:
            os.close(child)
            raise OSError("notice_directory")
        return child
    finally:
        os.close(parent)


def _timestamp(value, now):
    return (not isinstance(value, bool) and isinstance(value, (int, float)) and
            math.isfinite(value) and 0 <= now - value <= TTL_SECONDS)


def update_notice(event, plugin_root, running_version, config_dir, codex_binary=None):
    """Return a synchronous user-visible ``systemMessage`` once per new version.

    Unknown clients, versions, scope, unsafe metadata or contention are silent.
    The caller, never this helper, decides whether existing config is valid.
    """
    directory = fd = None
    try:
        session = _session(event)
        running = _version(running_version)
        if session is None or running is None:
            return {}
        context = _client(plugin_root)
        if context is None:
            return {}
        client, base, cache = context
        key = hashlib.sha256(f"{client}/{session}".encode("ascii")).hexdigest()
        source = hashlib.sha256(f"{plugin_root}/{base}/{codex_binary}/{event.get('cwd', '')}".encode("utf-8")).hexdigest()
        slot = f"{int(key[:8], 16) % MAX_SLOTS:03d}.json"
        directory = _state_directory(config_dir)
        fd = os.open(slot, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        if not _safe_file(fd):
            return {}
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not _linked(directory, slot, fd):
            return {}
        now = time.time()
        size = os.fstat(fd).st_size
        if size > MAX_BYTES:
            return {}
        record = json.loads(os.read(fd, MAX_BYTES + 1)) if size else {}
        if not isinstance(record, dict):
            return {}
        if record and record.get("key") != key:
            if _timestamp(record.get("touched"), now):
                return {}
            record = {}
        notices = record.get("notices", [])
        if not isinstance(notices, list) or len(notices) > MAX_NOTICES or any(not _version(v) for v in notices):
            return {}
        cached = (record.get("source") == source and _timestamp(record.get("checked"), now)
                  and now - record["checked"] < CACHE_SECONDS)
        installed = record.get("installed") if cached else None
        if not cached:
            try:
                installed = (_claude_installed(base, cache, event) if client == "claude"
                             else _codex_installed(codex_binary))
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError,
                    subprocess.SubprocessError, AttributeError):
                installed = None
        if installed is not None and not _version(installed):
            return {}
        notify = installed is not None and _version(installed) > running and installed not in notices
        if notify and len(notices) >= MAX_NOTICES:
            return {}
        if notify:
            notices.append(installed)
        record = dict(key=key, source=source, checked=record["checked"] if cached else now,
                      touched=now, installed=installed, notices=notices)
        data = json.dumps(record, separators=(",", ":"), allow_nan=False).encode("ascii")
        if len(data) > MAX_BYTES:
            return {}
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        if os.write(fd, data) != len(data):
            return {}
        os.fsync(fd)
        if not notify:
            return {}
        action = "Выполните /reload-plugins." if client == "claude" else "Начните новую сессию Codex."
        return {"systemMessage": f"subagent-model-router: установлен {installed}, этот хук запущен из {running_version}. "
                f"{action} Новая версия подтверждается только после запуска нового хука."}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, subprocess.SubprocessError, AttributeError):
        return {}
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)
