"""Private, exact-identity model pricing cache from official Markdown documents.

Prices are reference metadata in USD per million tokens. They are never used to
infer a price for an alias, a subscription, or an unlisted model.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

CACHE_SCHEMA = 1
TTL = 24 * 3600
TIMEOUT = 10
MAX_BYTES = 2 * 1024 * 1024
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}\Z")
SOURCES = {
    "codex": ("https://developers.openai.com/api/docs/pricing.md",),
    "claude": ("https://platform.claude.com/docs/en/about-claude/pricing.md",
               "https://platform.claude.com/docs/en/models/overview.md"),
}


def cache_path():
    return Path(os.path.expanduser("~/.cache/subagent-model-router/model-prices.json"))


def lock_path():
    return cache_path().with_suffix(".lock")


def _models(model_ids):
    if not isinstance(model_ids, (list, tuple, set)) or len(model_ids) > 512:
        return None
    if not all(isinstance(value, str) and MODEL_RE.fullmatch(value) for value in model_ids):
        return None
    return sorted(set(model_ids))


def _rate(cell, *, bare=False):
    if not isinstance(cell, str) or cell.strip() in ("", "-", "—", "N/A"):
        return None
    pattern = r"\$\s*([0-9]+(?:\.[0-9]+)?)" + (r"" if bare else r"\s*/\s*(?:1?M(?:Tokens?|Tok))")
    value = re.search(pattern, cell.replace(" ", ""), re.I)
    if value is None:
        return None
    number = float(value.group(1))
    return number if math.isfinite(number) and number >= 0 else None


def _cells(line):
    if not isinstance(line, str) or "|" not in line:
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return cells if cells and len(cells) <= 16 else None


def _table(markdown, heading):
    lines = markdown.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return []
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        cells = _cells(line)
        if cells:
            rows.append(cells)
    return rows


def parse_openai(markdown):
    """Parse only the official Standard pricing data table, by exact row ID."""
    rows = _table(markdown, "### Standard pricing data")
    header = ["Model", "Short context input", "Short context cached input", "Short context cache writes", "Short context output", "Long context input", "Long context cached input", "Long context cache writes", "Long context output"]
    if len(rows) < 3 or rows[0] != header:
        return {}
    result = {}
    for row in rows[2:]:
        if len(row) != 9:
            continue
        model = re.sub(r"\s*\(<[0-9]+K context length\)\s*\Z", "", row[0]).strip("`")
        if not MODEL_RE.fullmatch(model):
            continue
        rates, long_rates = [_rate(cell, bare=True) for cell in row[1:5]], [_rate(cell, bare=True) for cell in row[5:9]]
        if any(value is not None for value in rates):
            conditions = {"conditions_note": "Thresholds and promotional qualifiers are not parsed; consult source_url."}
            result[model] = dict(input=rates[0], cached_input=rates[1], cache_write=rates[2], output=rates[3],
                                 conditions=conditions, long_context=dict(input=long_rates[0], cached_input=long_rates[1],
                                                                   cache_write=long_rates[2], output=long_rates[3]))
    return result


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def parse_claude_overview(markdown):
    """Return official display-name -> API-ID pairs; no alias resolution."""
    for index, line in enumerate(markdown.splitlines()):
        header = _cells(line)
        if not header or len(header) < 2 or header[0] != "Feature":
            continue
        pairs = {}
        for detail in markdown.splitlines()[index + 1:index + 16]:
            row = _cells(detail)
            if row is None:
                break
            if not row or len(row) != len(header) or _slug(row[0]) not in ("claudeapiid", "claudeapialias"):
                continue
            for title, model in zip(header[1:], row[1:]):
                model = model.strip("`")
                if MODEL_RE.fullmatch(model) and model.startswith("claude-"):
                    pairs.setdefault(_slug(title), set()).add(model)
        if pairs:
            return pairs
    return {}


def parse_claude(pricing_markdown, overview_markdown):
    """Parse the official Model pricing table joined to official API IDs."""
    ids = parse_claude_overview(overview_markdown)
    rows = _table(pricing_markdown, "## Model pricing")
    header = ["Model", "Base input tokens", "5m cache writes", "1h cache writes", "Cache hits and refreshes", "Output tokens"]
    if len(rows) < 3 or rows[0] != header:
        return {}
    result = {}
    for row in rows[2:]:
        if len(row) != 6:
            continue
        models = ids.get(_slug(row[0]))
        if not models:
            continue
        rates = [_rate(cell) for cell in row[1:]]
        if any(value is not None for value in rates):
            for model in models:
                result[model] = dict(input=rates[0], cache_write=None, cached_input=rates[3], output=rates[4],
                                     conditions={"cache_write_5m": rates[1], "cache_write_1h": rates[2],
                                                 "conditions_note": "Thresholds and promotional qualifiers are not parsed; consult source_url."}, long_context=None)
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(url, timeout=TIMEOUT):
    request = urllib.request.Request(url, headers={"Accept": "text/markdown", "User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeError, urllib.error.HTTPError):
        return None


def _safe_dir():
    directory = cache_path().parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise OSError("unsafe cache directory")
    return directory


def _load():
    try:
        with cache_path().open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if not 0 < len(raw) <= MAX_BYTES:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) and data.get("schema") == CACHE_SCHEMA and isinstance(data.get("agents"), dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _valid_rate(value):
    return value is None or isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _valid_condition(value):
    return _valid_rate(value) or isinstance(value, str) and len(value) <= 256


def _entry(record, now):
    if not isinstance(record, dict) or set(record) != {"checked_at", "checked_models", "source_urls", "models"}:
        return None
    stamp, urls, models = record["checked_at"], record["source_urls"], record["models"]
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp) or not -60 <= now - stamp:
        return None
    if (not isinstance(record["checked_models"], list) or _models(record["checked_models"]) is None
            or not isinstance(urls, list) or not urls or not all(url in sum((list(values) for values in SOURCES.values()), []) for url in urls)):
        return None
    if not isinstance(models, dict) or len(models) > 512:
        return None
    for model, stored in models.items():
        if not MODEL_RE.fullmatch(model) or not isinstance(stored, dict) or set(stored) != {"rates", "retrieved_at", "stale"}:
            return None
        rates = stored["rates"]
        if (not isinstance(stored["retrieved_at"], (int, float)) or isinstance(stored["retrieved_at"], bool)
                or not math.isfinite(stored["retrieved_at"]) or not isinstance(stored["stale"], bool)
                or not isinstance(rates, dict) or set(rates) != {"input", "output", "cached_input", "cache_write", "conditions", "long_context"}
                or not all(_valid_rate(rates[key]) for key in ("input", "output", "cached_input", "cache_write"))
                or not isinstance(rates["conditions"], dict) or not all(isinstance(key, str) and len(key) <= 64 and _valid_condition(value) for key, value in rates["conditions"].items())
                or rates["long_context"] is not None and (not isinstance(rates["long_context"], dict) or set(rates["long_context"]) != {"input", "output", "cached_input", "cache_write"} or not all(_valid_rate(value) for value in rates["long_context"].values()))):
            return None
    return record


def _store(data, directory):
    raw = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        return False
    fd, temporary = tempfile.mkstemp(prefix=".model-prices-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, cache_path())
        return True
    finally:
        try: os.unlink(temporary)
        except OSError: pass


def cached_prices(agent, model_ids, *, now=None):
    """Return one exact price/unknown record per requested identity."""
    models = _models(model_ids)
    if agent not in SOURCES or models is None:
        return {}
    stamp = time.time() if now is None else now
    record = _entry(_load().get("agents", {}).get(agent), stamp)
    if record is None:
        return {model: dict(model_id=model, basis="standard_api", status="unknown", retrieved_at=None,
                            source_url=None, unit="USD/1M tokens", input=None, output=None,
                            cached_input=None, cache_write=None, conditions={}, long_context=None) for model in models}
    result = {}
    for model in models:
        stored = record["models"].get(model)
        if stored is None:
            result[model] = dict(model_id=model, basis="standard_api", status="unknown", retrieved_at=None,
                                 source_url=record["source_urls"][0], unit="USD/1M tokens", input=None, output=None,
                                 cached_input=None, cache_write=None, conditions={}, long_context=None)
            continue
        result[model] = dict(stored["rates"], model_id=model, basis="standard_api",
                             status="stale" if stored["stale"] or stamp - stored["retrieved_at"] >= TTL else "fresh",
                             retrieved_at=stored["retrieved_at"], source_url=record["source_urls"][0], unit="USD/1M tokens")
    return result


def _ready(record, models, now):
    return record is not None and set(models).issubset(record["checked_models"]) and now - record["checked_at"] < TTL


def _record_failed_refresh(data, agent, models, previous, stamp, directory):
    agents = data.get("agents", {}) if isinstance(data.get("agents"), dict) else {}
    if previous is not None:
        for stored in previous["models"].values():
            stored["stale"] = True
        previous.update(checked_at=stamp, checked_models=sorted(set(previous["checked_models"]) | set(models)))
    else:
        agents[agent] = {"checked_at": stamp, "checked_models": models,
                         "source_urls": list(SOURCES[agent]), "models": {}}
    return _store({"schema": CACHE_SCHEMA, "agents": agents}, directory)


def _refresh_running():
    try:
        fd = os.open(lock_path(), os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def refresh_prices(agent, model_ids, *, fetch=_fetch, now=None, force=False):
    """Fetch one complete official snapshot and atomically retain stale data on failure."""
    models = _models(model_ids)
    if agent not in SOURCES or models is None:
        return False
    fd = None
    try:
        directory = _safe_dir()
        fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fd is not None:
            os.close(fd)
        return False
    try:
        data = _load()
        stamp = time.time() if now is None else now
        previous = _entry(data.get("agents", {}).get(agent), stamp)
        if not force and _ready(previous, models, stamp):
            return True
        pages = [fetch(url) for url in SOURCES[agent]]
        if any(not isinstance(page, str) for page in pages):
            _record_failed_refresh(data, agent, models, previous, stamp, directory)
            return False
        parsed = parse_openai(pages[0]) if agent == "codex" else parse_claude(*pages)
        if not parsed:
            _record_failed_refresh(data, agent, models, previous, stamp, directory)
            return False
        agents = data.get("agents", {}) if isinstance(data.get("agents"), dict) else {}
        retained = {} if previous is None else dict(previous["models"])
        for stored in retained.values(): stored["stale"] = True
        retained.update({model: {"rates": rates, "retrieved_at": stamp, "stale": False} for model, rates in parsed.items()})
        agents[agent] = {"checked_at": stamp, "checked_models": models, "source_urls": list(SOURCES[agent]), "models": retained}
        return _store({"schema": CACHE_SCHEMA, "agents": agents}, directory)
    except (OSError, ValueError, TypeError):
        return False
    finally:
        try: os.close(fd)
        except OSError: pass


def ensure_prices(agent, model_ids, force=False):
    """Start one private worker when a current exact snapshot is missing or stale."""
    models = _models(model_ids)
    if agent not in SOURCES or models is None:
        return False
    now = time.time()
    if not force and _ready(_entry(_load().get("agents", {}).get(agent), now), models, now):
        return True
    if _refresh_running():
        return True
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "refresh", agent, json.dumps(models), "1" if force else "0"], cwd="/",
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "refresh":
        try: requested = json.loads(sys.argv[3])
        except ValueError: requested = None
        raise SystemExit(0 if refresh_prices(sys.argv[2], requested, force=sys.argv[4] == "1") else 1)
    raise SystemExit(2)
