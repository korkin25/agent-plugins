"""Opt-in exact Claude Agent initiating-model lookup; no conversation output.

The caller must enforce explicit consent before invoking this reader. Only the
event's own projects transcript is opened, with one bounded retry for delayed
append. At most 2 MiB is read and 100 ms is deliberately waited per invocation.
This is observational metadata, never a model-selection authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import time

from router_claude_state import _model, _session

_TAIL_BYTES = 1024 * 1024
_RETRY_SECONDS = 0.1
_TOOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}\Z")


def _identity(event, claude_home):
    session = _session(event)
    if (session is None or event.get("hook_event_name") != "PreToolUse"
            or event.get("tool_name") != "Agent"):
        return None
    tool_id = event.get("tool_use_id")
    transcript = event.get("transcript_path")
    if (not isinstance(tool_id, str) or not _TOOL_ID.fullmatch(tool_id)
            or not isinstance(transcript, str) or not 1 <= len(transcript) <= 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in transcript)):
        return None
    root = Path(claude_home if claude_home is not None else
                os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    path = Path(transcript)
    if any(not p.is_absolute() or ".." in p.parts or len(p.parts) > 64
           or len(str(p)) > 4096 for p in (root, path)):
        return None
    relative = path.relative_to(root / "projects")
    if len(relative.parts) < 2 or path.name != session + ".jsonl":
        return None
    return session, tool_id, path


def _read_tail(path):
    """Open only the supplied file; descriptor walks never follow symlinks."""
    directory = fd = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        directory = os.open("/", directory_flags)
        for component in path.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise OSError("unsafe_transcript")
        count = min(info.st_size, _TAIL_BYTES)
        offset = info.st_size - count
        os.lseek(fd, offset, os.SEEK_SET)
        data = os.read(fd, count)
        # Never interpret a prefix cut from the middle of an older JSON line.
        if offset:
            _, _, data = data.partition(b"\n")
        return data
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def _exact_model(data, session, tool_id):
    """Return (matched, model); an invalid/conflicting exact match is final."""
    found = None
    for line in data.splitlines():
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            continue
        if (not isinstance(record, dict) or record.get("type") != "assistant"
                or record.get("sessionId") != session):
            continue
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list) or not any(
                isinstance(block, dict) and block.get("type") == "tool_use"
                and block.get("name") == "Agent" and block.get("id") == tool_id
                for block in content):
            continue
        model = message.get("model")
        if not _model(model) or (found is not None and found != model):
            return True, None
        found = model
    return found is not None, found


def resolve_tool_model(event, claude_home=None) -> dict:
    """Return exact ``{model, source}`` or {}; never return transcript content.

    No directory scans, other sessions, configuration reads, network, or writes.
    One 100 ms retry is allowed only for an absent file or no exact match. I/O
    latency is OS-dependent; the deliberate wait and read volume are bounded.
    """
    try:
        identity = _identity(event, claude_home)
        if identity is None:
            return {}
        session, tool_id, path = identity
        for attempt in range(2):
            try:
                data = _read_tail(path)
            except FileNotFoundError:
                data = b""
            matched, model = _exact_model(data, session, tool_id)
            if matched:
                return {"model": model, "source": "transcript_tool_use"} if model else {}
            if attempt == 0:
                time.sleep(_RETRY_SECONDS)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return {}
