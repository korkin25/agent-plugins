"""Private aggregate-only VictoriaMetrics outbox; the hook never waits for HTTP.

Counters survive worker crashes. A pending wire snapshot is immutable until its
acknowledgement: an ambiguous HTTP failure retries identical values/timestamps.
Overflow coalesces event timing into counters; it does not retain raw events.
"""
from __future__ import annotations

import fcntl
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TELEMETRY_DEFAULTS = dict(backend="local", write_url="", query_url="", instance="default",
                          token_file="", flush_interval_seconds=5, timeout_seconds=3,
                          max_queue_events=1000, projects={}, user="")
MAX_SERIES = 4096
MAX_BODY_BYTES = 2 * 1024 * 1024
LATENCY_BUCKETS = (.01, .025, .05, .1, .25, .5, 1, 2, 4, 8, 16, 30)
PROBABILITY_BUCKETS = (.1, .25, .5, .7, .75, .9, .95, 1)
_DB_OPEN_LOCK = threading.Lock()


class TelemetryError(Exception):
    """Only fixed, non-secret diagnostic codes leave this module."""


def _url(value, write=False):
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("telemetry URL invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        valid = (parsed.scheme in ("http", "https") and parsed.hostname and "@" not in parsed.netloc and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment)
        parsed.port
    except ValueError:
        valid = False
    if not valid or (write and not parsed.path.rstrip("/").endswith("/api/v1/import/prometheus")):
        raise ValueError("telemetry URL invalid")
    return value.rstrip("/")


def validate_config(section):
    if not isinstance(section, dict) or set(section) - set(TELEMETRY_DEFAULTS):
        raise ValueError("telemetry configuration invalid")
    cfg = dict(TELEMETRY_DEFAULTS, **section)
    if cfg["backend"] not in ("local", "victoriametrics", "off"):
        raise ValueError("telemetry backend invalid")
    if not isinstance(cfg["instance"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", cfg["instance"]):
        raise ValueError("telemetry instance invalid")
    if not isinstance(cfg["user"], str) or (cfg["user"] and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", cfg["user"])):
        raise ValueError("telemetry user invalid")
    for key, low, high in (("flush_interval_seconds", .1, 60), ("timeout_seconds", .1, 10),
                           ("max_queue_events", 1, 100000)):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("telemetry limits invalid")
    if not isinstance(cfg["max_queue_events"], int):
        raise ValueError("telemetry queue limit invalid")
    if not isinstance(cfg["token_file"], str) or any(ord(c) < 32 for c in cfg["token_file"]):
        raise ValueError("telemetry token file invalid")
    if not isinstance(cfg["projects"], dict) or len(cfg["projects"]) > 256:
        raise ValueError("telemetry projects invalid")
    projects = {}
    for root, label in cfg["projects"].items():
        if (not isinstance(root, str) or not os.path.isabs(root) or any(ord(c) < 32 for c in root)
                or not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", label)):
            raise ValueError("telemetry projects invalid")
        projects[os.path.realpath(root)] = label
    cfg["projects"] = projects
    for key in ("write_url", "query_url"):
        if cfg[key]:
            cfg[key] = _url(cfg[key], write=key == "write_url")
        elif not isinstance(cfg[key], str) or (cfg["backend"] == "victoriametrics"):
            raise ValueError("telemetry URLs required")
    return cfg


def resolve_project(cwd, cfg):
    """Resolve a portable cohort without reading repository config or remotes.

Explicit absolute-root mappings win by longest component-prefix. Otherwise a
repository's directory name is the cohort. A .git file marks a linked worktree
without reading its contents. Identical names intentionally share a cohort;
use explicit mappings when names collide or differ between machines.
"""
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return "unknown"
    try:
        path = Path(cwd).resolve()
        for root, label in sorted(cfg.get("projects", {}).items(), key=lambda pair: len(pair[0]), reverse=True):
            if path == Path(root) or Path(root) in path.parents:
                return label
        project = path
        for parent in (path, *path.parents):
            if (parent / ".git").is_dir() or (parent / ".git").is_file():
                project = parent
                break
        return re.sub(r"[^A-Za-z0-9_.:-]+", "_", project.name).strip("_.:-")[:80] or "unknown"
    except (OSError, RuntimeError, ValueError):
        return "unknown"


def resolve_user(cfg):
    """Explicit alias or local login name, never a full name or account lookup."""
    if cfg.get("user"):
        return cfg["user"]
    try:
        return re.sub(r"[^A-Za-z0-9_.:-]+", "_", getpass.getuser()).strip("_.:-")[:80] or "unknown"
    except (OSError, KeyError, ImportError):
        return "unknown"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _token(path):
    if not path:
        return None
    try:
        fd = os.open(os.path.expanduser(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as fh:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise TelemetryError("token_permissions")
            raw = fh.read(4097)
        value = raw.decode("ascii").strip()
        if not value or len(raw) > 4096 or not re.fullmatch(r"[\x21-\x7e]+", value):
            raise TelemetryError("token_invalid")
        return value
    except TelemetryError:
        raise
    except Exception:
        raise TelemetryError("token_unavailable") from None


def request(cfg, url, body=None):
    """Bounded wall-clock HTTP including DNS; never redirects or ambient proxies.

The caller supplies a URL derived from its validated configured endpoint. Query
parameters may be present here (the configuration itself cannot contain them).
"""
    results = queue.Queue(maxsize=1)

    def exchange():
        try:
            headers = {"Content-Type": "text/plain; version=0.0.4"} if body is not None else {}
            token = _token(cfg.get("token_file", ""))
            if token:
                headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(url, data=body, headers=headers)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(req, timeout=cfg["timeout_seconds"]) as response:
                result = response.read(MAX_BODY_BYTES + 1)
                if len(result) > MAX_BODY_BYTES:
                    raise TelemetryError("response_size")
            results.put((True, result))
        except TelemetryError as exc:
            results.put((False, str(exc)))
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            results.put((False, "http_" + str(code)))
        except Exception:
            results.put((False, "network"))

    threading.Thread(target=exchange, daemon=True).start()
    try:
        ok, value = results.get(timeout=cfg["timeout_seconds"])
    except queue.Empty:
        raise TelemetryError("timeout") from None
    if not ok:
        raise TelemetryError(value)
    return value


def _paths(cfg, state_dir):
    root = Path(state_dir) if state_dir is not None else Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "subagent-model-router" / "telemetry"
    # This identifies the configured destination, never a task/session/working directory.
    destination = hashlib.sha256((cfg["write_url"] + "\0" + cfg["instance"]).encode()).hexdigest()[:24]
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return root / (destination + ".sqlite3"), root / (destination + ".lock")


def _db(cfg, state_dir=None):
    path, _ = _paths(cfg, state_dir)
    # Closing any non-SQLite descriptor to an existing DB inode releases this
    # process's POSIX record locks, including locks held by another connection.
    # Only a newly created inode may be opened/closed here. Serialize creation
    # with connect so another local thread cannot connect before that close.
    with _DB_OPEN_LOCK:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise TelemetryError("state_permissions")
        # The enclosing directory is private. chmod does not open/close the
        # inode, and SQLite manages the lifetime of every existing descriptor.
        path.chmod(0o600)
        conn = sqlite3.connect(path, timeout=.1, isolation_level=None)
    try:
        conn.execute("PRAGMA secure_delete=ON")
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            conn.executescript("""
        CREATE TABLE IF NOT EXISTS series (name TEXT PRIMARY KEY, value REAL NOT NULL,
            born INTEGER NOT NULL, baseline INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY CHECK(id=1),
            payload BLOB NOT NULL, stamp INTEGER NOT NULL, revision INTEGER NOT NULL);
        PRAGMA user_version=1;
            """)
    except Exception:
        conn.close()
        raise
    return conn


def _get(db, key, default=0):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def _enum(value, allowed, fallback="unknown"):
    return value if isinstance(value, str) and value in allowed else fallback


def _reason(value):
    base = str(value or "").split(";", 1)[0]
    allowed = {"explicit", "fork", "type", "excluded", "off", "no_key"}
    allowed.update("rule:" + rule for rule in ("light", "standard", "heavy", "risky", "review"))
    allowed.update("error:" + kind for kind in ("input", "config", "timeout", "network", "size", "internal", "json", "answers", "type", "range", "options", "sum"))
    if base in allowed:
        return base
    if re.fullmatch(r"error:http_[1-5][0-9]{2}", base):
        return base
    return "unknown"


def _metric(name, labels):
    return "smr_" + name + "{" + ",".join(key + "=" + json.dumps(str(value), ensure_ascii=True) for key, value in sorted(labels.items())) + "}"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _points(cfg, record, duration):
    project = record.get("project")
    if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", project):
        project = "unknown"
    user = record.get("user")
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", user):
        user = "unknown"
    labels = dict(instance=cfg["instance"], agent=_enum(record.get("agent"), {"claude", "codex"}), project=project, user=user)
    provider = _enum(record.get("provider"), {"typesafe", "openrouter"})
    reason = _reason(record.get("reason"))
    model = record.get("model")
    if model is None:
        model = "unchanged"
    elif not isinstance(model, str) or not re.fullmatch(r"(?:gpt-[a-z0-9.-]{1,48}|claude-[a-z0-9.-]{1,48}|haiku|sonnet|opus|inherit)", model):
        model = "other"
    call = dict(labels, provider=provider, reason=reason, model=model,
                mode=_enum(record.get("mode"), {"active", "shadow"}),
                tier=_enum(record.get("tier"), {"light", "standard", "heavy"}, "none"),
                effort=_enum(record.get("effort"), {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "inherit"}, "unchanged"),
                applied="true" if record.get("applied") is True else "false")
    points = {_metric("calls_total", call): 1.0}

    def histogram(name, value, dimensions, buckets):
        if not _number(value):
            return
        for bound in buckets:
            points[_metric(name + "_bucket", dict(dimensions, le=str(bound)))] = float(value <= bound)
        points[_metric(name + "_bucket", dict(dimensions, le="+Inf"))] = 1.0
        points[_metric(name + "_sum", dimensions)] = float(value)
        points[_metric(name + "_count", dimensions)] = 1.0

    histogram("hook_duration_seconds", duration, labels, LATENCY_BUCKETS)
    latency = record.get("latency_ms")
    if _number(latency):
        outcome = reason.removeprefix("error:") if reason.startswith("error:") else "success"
        attempt = dict(labels, provider=provider, outcome=outcome)
        points[_metric("jev_requests_total", attempt)] = 1.0
        histogram("jev_request_duration_seconds", latency / 1000, attempt, LATENCY_BUCKETS)
    answers = record.get("answers")
    probs = answers.get("tier", {}) if isinstance(answers, dict) else {}
    if isinstance(probs, dict) and reason.startswith("rule:"):
        for tier in ("light", "standard", "heavy"):
            probability = probs.get(tier)
            if _number(probability) and probability <= 1:
                histogram("decision_probability", probability, dict(labels, provider=provider, tier=tier), PROBABILITY_BUCKETS)
        for question in ("risky", "review"):
            probability = answers.get(question)
            if _number(probability) and probability <= 1:
                histogram("decision_" + question + "_probability", probability,
                          dict(labels, provider=provider), PROBABILITY_BUCKETS)
    return points


def enqueue(cfg, record, hook_duration_seconds, *, worker_command=None, state_dir=None):
    """Best-effort aggregate write; returns False on contention/storage failure.

max_queue_events bounds the pending event-count gauge. Excess events coalesce
into the same cumulative counters and increment coalesced_events (timing only).
"""
    if cfg.get("backend") != "victoriametrics":
        return False
    db = None
    try:
        points = _points(cfg, record, hook_duration_seconds)
        db = _db(cfg, state_dir)
        db.execute("BEGIN IMMEDIATE")
        revision = int(_get(db, "revision")) + 1
        count = db.execute("SELECT count(*) FROM series").fetchone()[0]
        existing = {row[0] for row in db.execute("SELECT name FROM series")}
        if count + len(set(points) - existing) > MAX_SERIES:
            _set(db, "dropped_events", int(_get(db, "dropped_events")) + 1)
        else:
            for name, value in points.items():
                db.execute("INSERT INTO series(name,value,born) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value", (name, value, revision))
            _set(db, "revision", revision)
            pending = int(_get(db, "pending_events"))
            _set(db, "pending_events", min(pending + 1, cfg["max_queue_events"]))
            if pending >= cfg["max_queue_events"]:
                _set(db, "coalesced_events", int(_get(db, "coalesced_events")) + 1)
        db.commit()
        if worker_command:
            _kick(cfg, worker_command, state_dir)
        return True
    except Exception:
        return False
    finally:
        if db is not None:
            db.close()


def _lock(cfg, state_dir):
    _, path = _paths(cfg, state_dir)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def _kick(cfg, command, state_dir):
    fd = _lock(cfg, state_dir)
    if fd is None:
        return
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    finally:
        os.close(fd)


def _prepare(db, cfg):
    db.execute("BEGIN IMMEDIATE")
    pending = db.execute("SELECT payload,stamp,revision FROM pending WHERE id=1").fetchone()
    if pending:
        db.commit()
        return pending
    rows = db.execute("SELECT name,value,baseline FROM series ORDER BY name").fetchall()
    if not rows:
        db.commit()
        return None
    stamp = max(int(time.time() * 1000), int(_get(db, "last_sample_ms")) + 2)
    revision = int(_get(db, "revision"))
    lines = []
    for name, value, baseline in rows:
        if not baseline:
            # A synthetic initial zero spans one flush interval. Batched events
            # have approximate timing, and a submillisecond jump would distort
            # rate() and be swallowed by common VM deduplication intervals.
            zero_stamp = stamp - int(max(1, cfg["flush_interval_seconds"]) * 1000)
            lines.append(f"{name} 0 {zero_stamp}\n")
        lines.append(f"{name} {value:.17g} {stamp}\n")
    health = {"telemetry_pending_events": int(_get(db, "pending_events")),
              "telemetry_coalesced_events_total": int(_get(db, "coalesced_events")),
              "telemetry_dropped_events_total": int(_get(db, "dropped_events")),
              "telemetry_last_success_timestamp_seconds": int(_get(db, "delivery_timestamp_ms")) / 1000}
    for name, value in health.items():
        lines.append(f'{_metric(name, dict(instance=cfg["instance"]))} {value:.17g} {stamp}\n')
    payload = "".join(lines).encode()
    if len(payload) > MAX_BODY_BYTES:
        db.rollback()
        raise TelemetryError("payload_size")
    db.execute("INSERT INTO pending VALUES(1,?,?,?)", (payload, stamp, revision))
    _set(db, "last_sample_ms", stamp)
    db.commit()
    return payload, stamp, revision


def flush_once(cfg, *, state_dir=None):
    """One immutable delivery attempt. Caller must hold worker lock."""
    db = _db(cfg, state_dir)
    try:
        pending = _prepare(db, cfg)
        if pending is None:
            return True
        payload, stamp, revision = pending
        try:
            request(cfg, cfg["write_url"], payload)
        except TelemetryError as exc:
            _set(db, "last_error", str(exc))
            return False
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE series SET baseline=1 WHERE born<=?", (revision,))
        db.execute("DELETE FROM pending WHERE id=1")
        _set(db, "delivered_revision", revision)
        _set(db, "delivery_timestamp_ms", int(time.time() * 1000))
        _set(db, "pending_events", min(cfg["max_queue_events"], max(0, int(_get(db, "revision")) - revision)))
        _set(db, "last_error", "")
        db.commit()
        return True
    finally:
        db.close()


def worker(cfg, *, state_dir=None, max_runtime_seconds=300, reload_config=None):
    """Finite detached singleton: heartbeat/retry until its lease expires.

After expiry snapshots remain durable and a later hook starts a new worker.
Idle series become stale in VM; this is deliberately not a resident service.
"""
    if cfg.get("backend") != "victoriametrics":
        return 0
    lock = _lock(cfg, state_dir)
    if lock is None:
        return 0
    deadline = time.monotonic() + max_runtime_seconds
    backoff = cfg["flush_interval_seconds"]
    try:
        while True:
            if reload_config is not None:
                try:
                    if reload_config() != cfg:
                        return 0
                except Exception:
                    return 0
            try:
                ok = flush_once(cfg, state_dir=state_dir)
            except Exception:
                ok = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 0
            backoff = cfg["flush_interval_seconds"] if ok else min(60, max(1, backoff * 2))
            time.sleep(min(backoff, remaining))
    finally:
        os.close(lock)


def snapshot(cfg, *, state_dir=None):
    """Local outbox health. Does not contact an endpoint or read raw journals."""
    db = _db(cfg, state_dir)
    try:
        result = {key: int(_get(db, key)) for key in ("revision", "delivered_revision", "pending_events", "coalesced_events", "dropped_events", "delivery_timestamp_ms")}
        result["last_error"] = _get(db, "last_error", "")
        result["series"] = db.execute("SELECT count(*) FROM series").fetchone()[0]
        result["pending_bytes"] = db.execute("SELECT COALESCE(sum(length(payload)),0) FROM pending").fetchone()[0]
        return result
    finally:
        db.close()
