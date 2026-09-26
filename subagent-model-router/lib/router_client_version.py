"""Actual Linux ancestor-client versions, captured once at session startup.

The hook only reads bounded process stat/exe metadata and private cache records.
SessionStart probes the retained native executable with --version once per
session/executable identity. Ordinary hooks only read the exact-session cache. No PATH lookup, cmdline, environment, or transcript
inspection. Cache records retain hashes, version, and time, never process paths.
Versions describe the latest startup observation for the agent/session UUID,
not continuous process inventory; simultaneous reuse of a UUID shares that scope.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import uuid
import time

from router_claude_state import _directory, _linked

CACHE_TTL = 24 * 60 * 60
PROBE_TIMEOUT = 2
MAX_OUTPUT = 512
MAX_RECORD = 512
MAX_SLOTS = 64
MAX_ANCESTORS = 8
_VERSION = r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9][A-Za-z0-9.+-]*)?"


def _version(value):
    return isinstance(value, str) and len(value) <= 80 and re.fullmatch(_VERSION, value) is not None


def _process(proc_root, pid):
    directory = Path(proc_root) / str(pid)
    if directory.stat().st_uid != os.geteuid():
        raise OSError("process_owner")
    fd = os.open(directory / "stat", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    if len(raw) > 4096 or not raw.startswith(str(pid).encode() + b" ("):
        raise ValueError("process_stat")
    fields = raw[raw.rindex(b") ") + 2:].split()
    parent, start = int(fields[1]), int(fields[19])
    if not 0 <= parent <= 2**31 - 1 or start < 0:
        raise ValueError("process_stat")
    return directory, parent, start


def _supported(path, agent):
    clean = path.removesuffix(" (deleted)")
    if not os.path.isabs(clean):
        return False
    name = Path(clean).name
    if name == agent or (agent == "codex" and re.fullmatch(r"codex-(?:x86_64|aarch64)-unknown-linux-(?:gnu|musl)", name)):
        return True
    # Official native Claude installs use a version-number executable filename.
    return (agent == "claude" and _version(name)
            and Path(clean).parent.name == "versions" and Path(clean).parent.parent.name == "claude")


def _ancestor(agent, proc_root):
    pid = os.getppid()
    seen = set()
    for _ in range(MAX_ANCESTORS):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        directory, parent, started = _process(proc_root, pid)
        path = os.readlink(directory / "exe")
        if _supported(path, agent):
            fd = os.open(directory / "exe", os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
                        or info.st_mode & 0o022 or not info.st_mode & 0o111
                        or os.read(fd, 4) != b"\x7fELF"):
                    raise OSError("executable_permissions")
                if _process(proc_root, pid)[1:] != (parent, started):
                    raise OSError("process_changed")
                current = os.stat(directory / "exe")
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise OSError("executable_changed")
                identity = (agent, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                key = hashlib.sha256(repr(identity).encode("ascii")).hexdigest()
                return fd, key
            except BaseException:
                os.close(fd)
                raise
        pid = parent
    return None


def _safe_cache(fd):
    info = os.fstat(fd)
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_mode & 0o777 == 0o600 and info.st_nlink == 1)


def _session_key(agent, event):
    if agent not in ("claude", "codex") or not isinstance(event, dict) or event.get("agent_id") is not None:
        return None
    session = event.get("session_id")
    if not isinstance(session, str) or len(session) != 36:
        return None
    parsed = uuid.UUID(session)
    if parsed.version not in range(1, 9) or str(parsed) != session.lower():
        return None
    return hashlib.sha256((agent + ":" + str(parsed)).encode("ascii")).hexdigest()


def _root(state_root):
    if state_root is not None:
        return state_root
    configured = os.environ.get("SUBAGENT_MODEL_ROUTER_CONFIG")
    if configured:
        return Path(configured).parent / "client-versions"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "subagent-model-router/client-versions"


def _cached(fd, key):
    if not _safe_cache(fd) or not 0 < os.fstat(fd).st_size <= MAX_RECORD:
        return {}
    os.lseek(fd, 0, os.SEEK_SET)
    record = json.loads(os.read(fd, MAX_RECORD + 1))
    if not isinstance(record, dict) or record.get("key") != key:
        return {}
    version, updated = record.get("version"), record.get("updated")
    if version is not None and not _version(version):
        return {}
    if isinstance(updated, bool) or not isinstance(updated, (float, int)) or not math.isfinite(updated):
        return {}
    return record if 0 <= time.time() - updated <= CACHE_TTL else {}


def _store(fd, key, executable, version):
    raw = json.dumps(dict(key=key, executable=executable, version=version, updated=time.time()),
                     separators=(",", ":")).encode("ascii")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    if len(raw) > MAX_RECORD or os.write(fd, raw) != len(raw):
        raise OSError("cache_write")


def _slot(key):
    return f"{int(key[:4], 16) % MAX_SLOTS:02d}.json"


def _invalidate(key, state_root):
    directory = None
    try:
        directory = _directory(_root(state_root), create=False)
        os.unlink(_slot(key), dir_fd=directory)
    except (OSError, ValueError, TypeError):
        pass
    finally:
        if directory is not None:
            os.close(directory)


def invalidate_client_version(agent, event, *, state_root=None) -> None:
    """Missing-config SessionStart invalidates prior evidence without probing."""
    try:
        key = _session_key(agent, event)
        if key is not None and event.get("hook_event_name") == "SessionStart":
            _invalidate(key, state_root)
    except (OSError, ValueError, TypeError):
        pass


def initialize_client_version(agent, event, *, proc_root="/proc", state_root=None) -> str | None:
    """SessionStart only: bounded exact-binary probe, once per session/identity.

    Call after configuration validation. Positive and unknown startup observations
    live for 24h; a repeated startup with unchanged executable never re-probes.
    """
    directory = cache_fd = executable_fd = key = None
    try:
        key = _session_key(agent, event)
        if key is None or event.get("hook_event_name") != "SessionStart":
            return None
        found = _ancestor(agent, proc_root)
        if found is None:
            _invalidate(key, state_root)
            return None
        executable_fd, executable = found
        directory = _directory(_root(state_root), create=True)
        cache_fd = os.open(_slot(key), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory)
        if not _safe_cache(cache_fd):
            return None
        try:
            fcntl.flock(cache_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        try:
            record = _cached(cache_fd, key)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            record = {}
        if record and record.get("executable") == executable:
            return record.get("version")
        # Interrupted or failed probing leaves unknown, never the previous version.
        _store(cache_fd, key, executable, None)
        version = _probe(agent, executable_fd)
        _store(cache_fd, key, executable, version)
        return version
    except (OSError, ValueError, TypeError, IndexError, UnicodeError, RecursionError):
        if key is not None:
            _invalidate(key, state_root)
        return None
    finally:
        for fd in (cache_fd, executable_fd, directory):
            if fd is not None:
                os.close(fd)


def resolve_client_version(agent, event, *, state_root=None) -> str | None:
    """Read exact-session startup metadata only; never inspect processes or spawn."""
    directory = fd = None
    try:
        key = _session_key(agent, event)
        if key is None:
            return None
        directory = _directory(_root(state_root), create=False)
        fd = os.open(_slot(key), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not _safe_cache(fd):
            return None
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        record = _cached(fd, key)
        return record.get("version") if _linked(directory, _slot(key), fd) else None
    except (OSError, ValueError, TypeError, IndexError, UnicodeError, RecursionError):
        return None
    finally:
        for handle in (fd, directory):
            if handle is not None:
                os.close(handle)


def _probe(agent, executable_fd):
    """Bound bytes and wall time; argv[0] keeps native CLI dispatch semantics."""
    child = None
    try:
        child = subprocess.Popen([agent, "--version"], executable=f"/proc/self/fd/{executable_fd}",
                                 pass_fds=(executable_fd,), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd="/",
                                 env={"PATH": "/usr/bin:/bin", "LANG": "C"}, start_new_session=True)
        deadline = time.monotonic() + PROBE_TIMEOUT
        output = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                return None
            chunk = os.read(child.stdout.fileno(), MAX_OUTPUT + 1 - len(output))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > MAX_OUTPUT:
                return None
        if child.wait(timeout=max(.001, deadline - time.monotonic())) != 0:
            return None
        text = output.decode("ascii").strip()
        pattern = (rf"({_VERSION}) \(Claude Code\)" if agent == "claude" else rf"codex-cli ({_VERSION})")
        match = re.fullmatch(pattern, text)
        return match[1] if match and _version(match[1]) else None
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        return None
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
            child.stdout.close()
