"""Bounded read-only lookup of a Codex ``turn_context`` metadata record.

This is observational metadata for one already-authorized hook session.  It is
not a configuration fallback and never uses another turn as a substitute.
"""
from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import stat
import uuid
from pathlib import Path


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}$")
_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_TAIL_BYTES = 2 * 1024 * 1024
_TOTAL_BYTES = 4 * 1024 * 1024
_MAX_FILES = 16


def _uuid(value: object, version: int | None = None) -> str | None:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return str(parsed) if version is None or parsed.version == version else None


def _owned_directory(path: Path) -> bool:
    """Directories are owned by the caller and every component is non-symlink."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid == os.geteuid()


def _candidate_days(session_id: str) -> tuple[_datetime.date, ...]:
    # UUIDv7's first 48 bits are Unix milliseconds, bounding the lookup route.
    millis = int(session_id.replace("-", "")[:12], 16)
    try:
        today = _datetime.datetime.fromtimestamp(millis / 1000, _datetime.timezone.utc).date()
    except (OSError, ValueError, OverflowError):
        return ()
    return tuple(today + _datetime.timedelta(days=offset) for offset in (-1, 0, 1))


def _session_file(root: Path, session_id: str) -> Path | None:
    """Find exactly one safe session file; duplicate filenames are ambiguous."""
    if not _owned_directory(root):
        return None
    sessions = root / "sessions"
    if not _owned_directory(sessions):
        return None
    found: list[Path] = []
    for day in _candidate_days(session_id):
        year, month, date = sessions / f"{day:%Y}", None, None
        month = year / f"{day:%m}"
        date = month / f"{day:%d}"
        if not (_owned_directory(year) and _owned_directory(month) and _owned_directory(date)):
            continue
        try:
            matches = sorted(date.glob("*" + session_id + ".jsonl"))
        except OSError:
            continue
        for path in matches[:_MAX_FILES]:
            if path.name.endswith(session_id + ".jsonl"):
                found.append(path)
        if len(found) > 1:
            return None
    return found[0] if len(found) == 1 else None


def _read_tail(path: Path, remaining: int) -> bytes | None:
    """Open a single owner-owned regular file without following a symlink."""
    try:
        before = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid != os.geteuid():
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size <= 0:
            return None
        count = min(info.st_size, _TAIL_BYTES, remaining)
        os.lseek(fd, -count, os.SEEK_END)
        return os.read(fd, count)
    except OSError:
        return None
    finally:
        os.close(fd)


def _exact_payloads(data: bytes, turn_id: str):
    for line in data.splitlines():
        # Cheap marker avoids JSON parsing arbitrary transcript records.
        if b'"type"' not in line or b'turn_context' not in line or b'"turn_id"' not in line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError, TypeError):
            continue
        payload = record.get("payload") if isinstance(record, dict) and record.get("type") == "turn_context" else None
        if isinstance(payload, dict) and payload.get("turn_id") == turn_id:
            yield payload


def resolve_codex_turn(event: dict, codex_home: str | os.PathLike[str] | None = None) -> dict:
    """Return exact ``{model, effort, source}`` metadata or fail closed with ``{}``."""
    if not isinstance(event, dict):
        return {}
    session_id = _uuid(event.get("session_id"), version=7)
    turn_id = _uuid(event.get("turn_id"))
    model = event.get("model")
    if not session_id or not turn_id or not isinstance(model, str) or not _MODEL.fullmatch(model):
        return {}
    root = Path(codex_home if codex_home is not None else os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    path = _session_file(root, session_id)
    if path is None:
        return {}
    data = _read_tail(path, _TOTAL_BYTES)
    if data is None:
        return {}
    payloads = list(_exact_payloads(data, turn_id))
    if not payloads:
        return {}
    # The append-most-recent exact record is authoritative; invalid metadata must
    # never fall back to an older exact record.
    payload = payloads[-1]
    effort = payload.get("effort")
    if payload.get("model") != model or not isinstance(effort, str) or effort not in _EFFORTS:
        return {}
    return {"model": model, "effort": effort, "source": "turn_context"}
