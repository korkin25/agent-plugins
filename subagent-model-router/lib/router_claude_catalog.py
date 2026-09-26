"""Native Claude SDK model metadata, without any user/model turn or session data.

Only supported Agent aliases, model descriptions, resolved IDs, and effort
capabilities survive parsing. Account metadata from initialize is discarded.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time

ALIASES = ("haiku", "sonnet", "opus", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Source: https://code.claude.com/docs/en/model-config#choose-an-effort-level
# These describe the native effort setting, not a task difficulty classifier.
EFFORT_SOURCE = "https://code.claude.com/docs/en/model-config#choose-an-effort-level"
EFFORT_DESCRIPTIONS = {
    "low": "Reserve for short, scoped, latency-sensitive tasks that are not intelligence-sensitive.",
    "medium": "Reduces token usage for cost-sensitive work that can trade off some intelligence.",
    "high": "Balances token usage and intelligence.",
    "xhigh": "Deeper reasoning at higher token spend.",
    "max": "Can improve performance on demanding tasks but may show diminishing returns and is prone to overthinking. Test before adopting broadly.",
}

TIMEOUT = 30
MAX_BYTES = 2 * 1024 * 1024
REQUEST_ID = "subagent-model-router-catalog"
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}")
CACHE_SCHEMA = 2


class NativeCatalog(dict):
    def __init__(self, models=(), inventory=(), missing_descriptions=()):
        super().__init__(models)
        self.inventory = sorted(set(inventory))
        self.missing_descriptions = sorted(set(missing_descriptions))


def _alias(value):
    if value in ALIASES:
        return value
    if value in ("opus[1m]", "opus[200k]", "sonnet[1m]", "sonnet[200k]"):
        return value.partition("[")[0]
    match = re.fullmatch(r"claude-(haiku|sonnet|opus|fable)-[A-Za-z0-9._-]+(?:\[(?:1m|200k)\])?", value)
    return match.group(1) if match else None


def parse_models(models, redact=lambda value: value, previous=None):
    """Normalize unambiguous native rows; an exact canonical alias takes precedence."""
    if not isinstance(models, list):
        return None
    groups, inventory, missing_descriptions = {}, set(), set()
    for row in models:
        if not isinstance(row, dict) or not isinstance(row.get("value"), str):
            continue
        value = row["value"]
        alias = _alias(value)
        if alias is None:
            continue
        description = row.get("description")
        resolved = row.get("resolvedModel")
        identity = resolved if isinstance(resolved, str) and MODEL_ID.fullmatch(resolved) else value
        prior = previous.get(alias) if previous is not None else None
        if (not isinstance(description, str) or not description.strip()) and prior and isinstance(resolved, str) and prior["resolved_model"] == resolved:
            description = prior["description"]
        inventory.add(identity)
        if not isinstance(description, str) or not description.strip():
            missing_descriptions.add(identity)
        supports = row.get("supportsEffort", False)
        levels = row.get("supportedEffortLevels", [])
        valid = (isinstance(description, str) and bool(description.strip()) and
                 isinstance(supports, bool) and isinstance(levels, list) and
                 all(isinstance(level, str) and level in EFFORTS for level in levels) and
                 (resolved is None or isinstance(resolved, str) and MODEL_ID.fullmatch(resolved)) and
                 (bool(levels) if supports else not levels))
        entry = None
        if valid:
            entry = {"catalog_value": value, "resolved_model": resolved,
                     "description": redact(description[:4000]), "supports_effort": supports,
                     "supported_efforts": [level for level in EFFORTS if level in levels]}
        groups.setdefault(alias, []).append((value == alias, entry))
    catalog = NativeCatalog(inventory=inventory, missing_descriptions=missing_descriptions)
    for alias, rows in groups.items():
        exact = [entry for is_exact, entry in rows if is_exact]
        candidates = exact if exact else [entry for _, entry in rows]
        if candidates and candidates[0] is not None and all(entry == candidates[0] for entry in candidates):
            catalog[alias] = candidates[0]
    return catalog if catalog or catalog.inventory else None


def fetch_catalog(binary, timeout=TIMEOUT, redact=lambda value: value, previous=None):
    """Send only SDK initialize in an isolated private directory; bounded and reaped."""
    if not os.path.isabs(binary) or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        return None
    proc = None
    with tempfile.TemporaryDirectory(prefix="smr-claude-catalog-", dir="/var/tmp") as directory:
        os.chmod(directory, 0o700)
        config_dir = os.path.join(directory, "config")
        os.mkdir(config_dir, 0o700)
        env = {key: value for key, value in os.environ.items()
               if key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "LD_LIBRARY_PATH", "SYSTEMROOT")}
        env.update(HOME=directory, CLAUDE_CONFIG_DIR=config_dir, TMPDIR=directory)
        command = [binary, "--bare", "--setting-sources", "", "--strict-mcp-config", "--mcp-config",
                   '{"mcpServers":{}}', "--no-session-persistence", "-p", "--input-format", "stream-json",
                   "--output-format", "stream-json", "--verbose"]
        try:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, cwd=directory, env=env,
                                    start_new_session=True, bufsize=0)
            request = {"type": "control_request", "request_id": REQUEST_ID,
                       "request": {"subtype": "initialize"}}
            proc.stdin.write(json.dumps(request).encode() + b"\n")
            proc.stdin.flush()
            deadline, total, pending = time.monotonic() + timeout, 0, b""
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while time.monotonic() < deadline:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        break
                    chunk = os.read(proc.stdout.fileno(), min(65536, MAX_BYTES + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        return None
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        message = json.loads(line)
                        if not isinstance(message, dict) or message.get("type") != "control_response":
                            continue
                        response = message.get("response")
                        if not isinstance(response, dict) or response.get("request_id") != REQUEST_ID:
                            continue
                        result = response.get("response")
                        if response.get("subtype") != "success" or not isinstance(result, dict):
                            return None
                        return parse_models(result.get("models"), redact, previous)
        except (OSError, ValueError, TypeError):
            return None
        finally:
            if proc is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    proc.wait()
                proc.stdout.close()
    return None


def cache_path():
    return Path(os.path.expanduser("~/.cache/subagent-model-router/claude-models.json"))


def lock_path():
    return cache_path().with_suffix(".lock")


def _identity(binary):
    try:
        real = os.path.realpath(binary)
        return real, os.stat(real).st_mtime_ns
    except (OSError, ValueError):
        return None


def _entries():
    try:
        with cache_path().open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {}
        data = json.loads(raw)
    except (OSError, ValueError):
        return {}
    entries = data.get("binaries") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def _valid_catalog(catalog):
    if not isinstance(catalog, dict) or set(catalog) - set(ALIASES):
        return False
    raw = []
    for alias, item in catalog.items():
        if not isinstance(item, dict) or set(item) != {"catalog_value", "resolved_model", "description", "supports_effort", "supported_efforts"}:
            return False
        value = item["catalog_value"]
        if not isinstance(value, str) or _alias(value) != alias:
            return False
        raw.append({"value": value, "resolvedModel": item["resolved_model"], "description": item["description"],
                    "supportsEffort": item["supports_effort"], "supportedEffortLevels": item["supported_efforts"]})
    return not catalog or parse_models(raw) == catalog


def load_cached_catalog(binary, now=None, max_age=None):
    identity = _identity(binary)
    if identity is None:
        return None, None
    entry = _entries().get(identity[0])
    if not isinstance(entry, dict) or entry.get("schema") != CACHE_SCHEMA or entry.get("mtime_ns") != identity[1]:
        return None, None
    stamp = entry.get("ts")
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp):
        return None, None
    age = (time.time() if now is None else now) - stamp
    if age < -60 or (max_age is not None and age >= max_age) or not _valid_catalog(entry.get("models")):
        return None, None
    inventory, missing = entry.get("inventory"), entry.get("missing_descriptions")
    if (not isinstance(inventory, list) or not isinstance(missing, list) or
            not all(isinstance(value, str) and MODEL_ID.fullmatch(value) for value in inventory + missing)):
        return None, None
    return NativeCatalog(entry["models"], inventory, missing), max(0, age)


def _cache_dir():
    directory = cache_path().parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OSError("unsafe cache directory")
    return directory


def save_catalog(binary, catalog):
    identity = _identity(binary)
    if identity is None or not _valid_catalog(catalog):
        return False
    temporary = None
    try:
        now = time.time()
        entries = {path: row for path, row in _entries().items() if isinstance(row, dict) and
                   isinstance(row.get("ts"), (int, float)) and not isinstance(row["ts"], bool) and
                   math.isfinite(row["ts"])}
        entries[identity[0]] = {"schema": CACHE_SCHEMA, "mtime_ns": identity[1], "ts": now, "models": catalog,
                                "inventory": getattr(catalog, "inventory", []),
                                "missing_descriptions": getattr(catalog, "missing_descriptions", [])}
        fd, temporary = tempfile.mkstemp(prefix=".claude-models-", dir=_cache_dir())
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"binaries": entries}, stream, ensure_ascii=False)
        os.replace(temporary, cache_path())
        return True
    except (OSError, ValueError):
        return False
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def refresh_running():
    try:
        fd = os.open(lock_path(), os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def start_refresh(binary, command, force=False):
    if refresh_running():
        return True
    try:
        subprocess.Popen([*command, "refresh-claude-catalog", binary, *(["--force"] if force else [])], cwd="/",
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        return False
    return True


def refresh_catalog(binary, timeout=TIMEOUT, redact=lambda value: value, force=False, on_change=None):
    try:
        _cache_dir()
        fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        previous, _ = load_cached_catalog(binary)
        if previous is not None and not force:
            return True
        catalog = fetch_catalog(binary, timeout, redact, previous)
        if catalog is not None and previous is not None:
            for alias, info in catalog.items():
                old = previous.get(alias)
                if old and old["resolved_model"] == info["resolved_model"] and old["catalog_value"] == info["catalog_value"]:
                    info["description"] = old["description"]
        if catalog is None or not save_catalog(binary, catalog):
            return False
        if (previous is None or set(previous.inventory) != set(catalog.inventory) or
                set(previous.missing_descriptions) != set(catalog.missing_descriptions)) and on_change:
            on_change(catalog)
        return True
    finally:
        os.close(fd)
