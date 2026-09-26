"""Private Claude lifecycle checkpoints, never transcript/config inference.

Only SessionStart/PostModelSwitch supply model evidence. A conservative 24-hour
TTL makes long sessions unknown until another lifecycle checkpoint. Fixed hash
slots bound storage to 256 files of at most 2048 bytes; collisions lose evidence,
never borrow it. Paths are hashed as supplied and are never opened or retained.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

TTL_SECONDS = 24 * 60 * 60
MAX_SLOTS = 256
MAX_BYTES = 2048
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}\Z")
_SOURCES = {"session_start", "post_model_switch"}
_SWITCH_SOURCES = {"command", "picker", "sdk", "auto", "resume"}


def _model(value):
    return (isinstance(value, str) and bool(_MODEL.fullmatch(value))
            and value not in {"inherit", "default", "auto", "unknown"})


def _session(event):
    if not isinstance(event, dict) or "agent_id" in event or "turn_id" in event:
        return None
    session = event.get("session_id")
    if not isinstance(session, str) or len(session) != 36:
        return None
    try:
        parsed = uuid.UUID(session)
    except ValueError:
        return None
    if str(parsed) != session.lower() or parsed.version not in range(1, 9):
        return None
    return str(parsed)


def _slot(session):
    key = hashlib.sha256(session.encode("ascii")).digest()
    return f"{int.from_bytes(key[:2], 'big') % MAX_SLOTS:03d}.json"


def _identity(event):
    session = _session(event)
    if session is None:
        return None
    transcript = event.get("transcript_path")
    if (not isinstance(transcript, str) or not 1 <= len(transcript) <= 4096
            or not os.path.isabs(transcript) or any(ord(c) < 32 or ord(c) == 127 for c in transcript)):
        return None
    if Path(transcript).name != session + ".jsonl":
        return None
    try:
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    except UnicodeError:
        return None
    return session, digest, _slot(session)


def _directory(state_root, create):
    """Walk using directory descriptors: no ancestor symlinks or unsafe owners."""
    if state_root is None:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
        state_root = Path(base) / "subagent-model-router/claude-sessions"
    path = Path(state_root)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) > 64 or len(str(path)) > 4096:
        raise OSError("state_path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            # System temp directories are safe only with root-owned sticky bit;
            # all other ancestors must be non-writable to group/other.
            shared_temp = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not shared_temp):
                raise OSError("state_ancestor")
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o700:
            raise OSError("state_permissions")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _safe_file(fd):
    info = os.fstat(fd)
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_mode & 0o777 == 0o600 and info.st_nlink == 1)


def _linked(directory, name, fd):
    before, current = os.fstat(fd), os.stat(name, dir_fd=directory, follow_symlinks=False)
    return before.st_dev == current.st_dev and before.st_ino == current.st_ino


def _invalidate(directory, name, fd=None):
    # An unlinked contended writer can finish only on its old inode. New readers
    # cannot observe it. Never unlink a replacement created by another writer.
    try:
        if fd is None or _linked(directory, name, fd):
            os.unlink(name, dir_fd=directory)
    except OSError:
        pass


def _read(fd, identity):
    info = os.fstat(fd)
    if not _safe_file(fd) or not 0 < info.st_size <= MAX_BYTES:
        return {}
    os.lseek(fd, 0, os.SEEK_SET)
    record = json.loads(os.read(fd, MAX_BYTES + 1))
    if (not isinstance(record, dict) or record.get("version") != 1
            or record.get("session_id") != identity[0] or record.get("transcript_hash") != identity[1]
            or not _model(record.get("model")) or record.get("source") not in _SOURCES):
        return {}
    updated = record.get("updated")
    if (isinstance(updated, bool) or not isinstance(updated, (int, float)) or not math.isfinite(updated)
            or not 0 <= time.time() - updated <= TTL_SECONDS):
        return {}
    return record


def invalidate_session(event, state_root=None) -> None:
    """Discard a lifecycle checkpoint without creating state or reading content.

    Used when configuration cannot be loaded. Missing transcript metadata may
    still invalidate the UUID slot; a supplied path must be Claude-shaped.
    Collisions can only discard evidence, never attribute it to another session.
    """
    directory = None
    try:
        session = _session(event)
        if session is None or event.get("hook_event_name") not in {"SessionStart", "PostModelSwitch", "SessionEnd"}:
            return
        if event.get("transcript_path") is not None and _identity(event) is None:
            return
        directory = _directory(state_root, create=False)
        _invalidate(directory, _slot(session))
    except (OSError, ValueError, TypeError, UnicodeError):
        pass
    finally:
        if directory is not None:
            os.close(directory)


def update_session(event, state_root=None) -> None:
    """Consume an official lifecycle event; missing/invalid evidence invalidates.

    No network, transcript reads, dialogue storage, waiting for locks, or output.
    Invalidation precedes writes so interrupted/failed writes cannot preserve an
    older model. If even unlink fails, rejectable permissions/TTL still apply;
    no local cache can promise invalidation on a wholly unwritable filesystem.
    """
    directory = fd = None
    try:
        session = _session(event)
        if session is None or event.get("hook_event_name") not in {"SessionStart", "PostModelSwitch", "SessionEnd"}:
            return
        directory = _directory(state_root, create=True)
        name = _slot(session)
        identity = _identity(event)
        if identity is None:
            _invalidate(directory, name)
            return
        try:
            fd = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
        except OSError:
            _invalidate(directory, name)
            return
        if not _safe_file(fd):
            _invalidate(directory, name, fd)
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _invalidate(directory, name, fd)
            return
        previous = {}
        try:
            previous = _read(fd, identity)
        except (ValueError, UnicodeError, RecursionError):
            pass
        os.ftruncate(fd, 0)
        kind = event["hook_event_name"]
        model = event.get("model") if kind == "SessionStart" else event.get("to_model")
        if kind == "SessionStart" and "source" in event and event["source"] not in {"startup", "resume", "clear", "compact", "fork"}:
            model = None
        if kind == "SessionEnd" or not _model(model):
            _invalidate(directory, name, fd)
            return
        record = dict(version=1, session_id=identity[0], transcript_hash=identity[1],
                      model=model, source="session_start", updated=time.time())
        if kind == "PostModelSwitch":
            origin = event.get("from_model")
            if not _model(origin) or event.get("source") not in _SWITCH_SOURCES:
                _invalidate(directory, name, fd)
                return
            duplicate = (previous.get("source") == "post_model_switch" and previous.get("model") == model
                         and previous.get("from_model") == origin)
            if previous and previous["model"] != origin and not duplicate:
                _invalidate(directory, name, fd)
                return
            record.update(source="post_model_switch", from_model=origin)
        data = json.dumps(record, separators=(",", ":"), allow_nan=False).encode("ascii")
        os.lseek(fd, 0, os.SEEK_SET)
        if len(data) > MAX_BYTES or os.write(fd, data) != len(data):
            raise OSError("state_write")
        os.fsync(fd)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        if directory is not None and fd is not None:
            _invalidate(directory, name, fd)
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def resolve_session(event, state_root=None) -> dict:
    """Return exact-session ``{model, source}`` or unknown; never read transcripts."""
    directory = fd = None
    try:
        identity = _identity(event)
        if identity is None:
            return {}
        directory = _directory(state_root, create=False)
        fd = os.open(identity[2], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        if not _safe_file(fd):
            return {}
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        record = _read(fd, identity)
        if record and _linked(directory, identity[2], fd):
            return {"model": record["model"], "source": record["source"]}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        pass
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)
    return {}
