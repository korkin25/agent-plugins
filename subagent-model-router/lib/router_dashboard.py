"""Bounded VictoriaMetrics queries and a self-contained, script-free report.

Costs are provider-reported charges, never inferred savings or model quality.
Counters are window estimates (PromQL increase), not a replacement for a ledger.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import math
import os
import re
from pathlib import Path
import time
import urllib.parse

from router_telemetry import request, validate_config

MAX_SERIES = 120
MAX_POINTS = 241
COLORS = ("#73a7ff", "#52d6b0", "#bd95ff", "#ffbc66", "#ff7d98", "#5ed4ed")


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _decode(raw, ranged):
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("query failed")
    data = payload.get("data")
    expected = "matrix" if ranged else "vector"
    if not isinstance(data, dict) or data.get("resultType") != expected:
        raise ValueError("invalid query result")
    result = data.get("result")
    if not isinstance(result, list) or len(result) > MAX_SERIES:
        raise ValueError("query series limit exceeded")
    decoded = []
    for row in result:
        if not isinstance(row, dict) or not isinstance(row.get("metric"), dict):
            raise ValueError("invalid series")
        labels = row["metric"]
        if len(labels) > 20 or any(not isinstance(k, str) or not isinstance(v, str)
                                   or len(k) > 100 or len(v) > 256 for k, v in labels.items()):
            raise ValueError("invalid labels")
        points = row.get("values") if ranged else [row.get("value")]
        if not isinstance(points, list) or len(points) > MAX_POINTS:
            raise ValueError("query point limit exceeded")
        clean = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("invalid sample")
            timestamp, value = _number(point[0]), _number(point[1])
            if timestamp is None:
                raise ValueError("invalid timestamp")
            # NaN is common for empty histogram windows; retain the gap.
            clean.append([timestamp, value])
        decoded.append({"labels": labels, "points": clean})
    return decoded


def _value(row):
    return row["points"][-1][1] if row["points"] else None


def _total(rows):
    values = [_value(row) for row in rows if _value(row) is not None]
    return sum(values) if values else None


def _reporter_labels(labels):
    """Only explicit, safe observation metadata identifies a reporter."""
    return all(isinstance(labels.get(key), str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", labels[key])
               and labels[key] != "unknown" for key in ("host", "user", "plugin_version")) and labels.get("agent") in ("claude", "codex")


def _agent_version(value):
    return value if isinstance(value, str) and len(value) <= 80 and re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
        r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", value) else "unknown"


def hook_versions(rows, end):
    """Last hook time is the gauge value, never its heartbeat/export timestamp."""
    observed = {}
    for row in rows:
        labels, stamp = row["labels"], _value(row)
        if not _reporter_labels(labels) or stamp is None or not 0 < stamp <= end:
            continue
        identity = tuple(labels.get(key, "unknown") for key in ("instance", "host", "user", "agent", "plugin_version")) + (_agent_version(labels.get("agent_version")),)
        observed[identity] = max(stamp, observed.get(identity, 0))
    latest = {}
    for identity, stamp in observed.items():
        latest[identity[:4]] = max(stamp, latest.get(identity[:4], 0))
    result = []
    for identity, stamp in sorted(observed.items(), key=lambda item: (item[0][:4], -item[1], item[0][4:])):
        result.append(dict(zip(("instance", "host", "user", "agent", "plugin_version", "agent_version"), identity),
                           last_seen_timestamp=stamp, age_seconds=end - stamp,
                           latest_observed=stamp == latest[identity[:4]]))
    return result


def mixed_version_reporters(rows):
    versions = {}
    for row in rows:
        identity = tuple(row[key] for key in ("instance", "host", "user", "agent"))
        versions.setdefault(identity, set()).add((row["plugin_version"], row["agent_version"]))
    return sum(len(values) > 1 for values in versions.values()) if rows else None


VERSION_NOTE = ("Observed hook versions within instance/user/client filters, independent of project. "
                "Plugin version and invoking Claude Code/Codex client version are separate from the model; missing client versions remain unknown. "
                "Latest means most recent hook timestamp per reporter, not newest release. Historical versions remain visible. "
                "This is not an installed-version inventory; idle or unreported installations are unknown.")


def _percentile(rows, quantile):
    buckets = []
    for row in rows:
        try:
            boundary = float(row["labels"].get("le", ""))
        except ValueError:
            continue
        count = _value(row)
        if count is not None and count >= 0 and not math.isnan(boundary):
            buckets.append((boundary, count))
    buckets.sort()
    if not buckets or buckets[-1][0] != math.inf or buckets[-1][1] <= 0:
        return None
    target = quantile * buckets[-1][1]
    low, previous = 0.0, 0.0
    for high, count in buckets:
        count = max(previous, count)  # tolerate floating point histogram noise
        if count >= target:
            if math.isinf(high):
                return low
            return low + (high - low) * (target - previous) / (count - previous) if count > previous else high
        low, previous = high, count
    return None


def query_stats(cfg, days=7, project=None, user=None, agent=None, account=None):
    """Return serializable operational data; failures never become zero/no-data.

    Accept a full router config or its telemetry subsection. At most thirty-two
    bounded requests, at most three in parallel; server text/URLs are never
    included in errors or reports. The shared transport limits response bytes.
    """
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    if project is not None and (not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", project)):
        raise ValueError("project must be a safe cohort label")
    if user is not None and (not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", user)):
        raise ValueError("user must be a safe cohort label")
    if agent is not None and agent not in ("codex", "claude"):
        raise ValueError("agent must be codex or claude")
    config = validate_config(cfg.get("telemetry", cfg))
    account = account if account is not None else (config.get("account") or None)
    if account is not None and (not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", account)):
        raise ValueError("account must be a safe cohort label")
    if not config.get("query_url"):
        raise ValueError("telemetry.query_url is required")
    end = int(time.time())
    start = end - days * 86400
    step = max(60, math.ceil((end - start) / 240))
    selector = "{instance=" + json.dumps(config["instance"]) + "}"
    health_selector = selector
    if project is not None:
        selector = selector[:-1] + ",project=" + json.dumps(project) + "}"
    if user is not None:
        selector = selector[:-1] + ",user=" + json.dumps(user) + "}"
    if agent is not None:
        selector = selector[:-1] + ",agent=" + json.dumps(agent) + "}"
    version_selector = health_selector
    for key, value in (("user", user), ("agent", agent)):
        if value is not None:
            version_selector = version_selector[:-1] + "," + key + "=" + json.dumps(value) + "}"
    window = str(days * 86400) + "s"
    lookback = str(max(300, step * 2)) + "s"
    def inc(metric, span=window):
        return "increase(" + metric + selector + "[" + span + "])"
    queries = {
        "calls": (False, "sum by (host,plugin_version,agent_version,user,project,agent,mode,reason,tier,model,effort,applied) (" + inc("smr_calls_total") + ")"),
        "hook_versions": (False, "max by (instance,host,user,agent,plugin_version,agent_version) (last_over_time(smr_hook_version_last_seen_timestamp_seconds" + version_selector + "[" + window + "]))"),
        "requests": (False, "sum by (outcome) (" + inc("smr_jev_requests_total") + ")"),
        "jev_buckets": (False, "sum by (le) (" + inc("smr_jev_request_duration_seconds_bucket") + ")"),
        "hook_buckets": (False, "sum by (le) (" + inc("smr_hook_duration_seconds_bucket") + ")"),
        "request_rate": (True, "sum by (outcome) (rate(smr_jev_requests_total" + selector + "[" + lookback + "]))"),
        "model_rate": (True, "sum by (model) (rate(smr_calls_total" + selector[:-1] + ',reason=~"rule:.*"}[' + lookback + "]))"),
        "latency_p95": (True, "histogram_quantile(0.95, sum by (le) (rate(smr_jev_request_duration_seconds_bucket" + selector + "[" + lookback + "])))"),
        "pending_events": (False, "sum(last_over_time(smr_telemetry_pending_events" + health_selector + "[" + window + "]))"),
        "coalesced_events": (False, "sum(last_over_time(smr_telemetry_coalesced_events_total" + health_selector + "[" + window + "]))"),
        "dropped_events": (False, "sum(last_over_time(smr_telemetry_dropped_events_total" + health_selector + "[" + window + "]))"),
        "last_delivery": (False, "max(last_over_time(smr_telemetry_last_success_timestamp_seconds" + health_selector + "[" + window + "]))"),
        "jev_cost_usd": (False, "sum(" + inc("smr_jev_cost_usd_total") + ")"),
        "jev_known_cost_requests": (False, "sum(" + inc("smr_jev_known_cost_requests_total") + ")"),
        "jev_unpriced_requests": (False, "sum(" + inc("smr_jev_unpriced_requests_total") + ")"),
        "jev_cost_rate": (True, "3600 * sum(rate(smr_jev_cost_usd_total" + selector + "[" + lookback + "]))"),
        "jev_cost_rate_current": (False, "3600 * sum(rate(smr_jev_cost_usd_total" + selector + "[" + lookback + "]))"),
    }
    observation_metrics = ["jev_" + direction + suffix for direction in ("input", "output")
                           for suffix in ("_tokens", "_known_token_requests", "_unknown_token_requests")]
    observation_metrics += ["claude_model_lookup_" + suffix for suffix in
                            ("requests", "read_attempts", "bytes_read", "duration_seconds",
                             "api_input_tokens", "api_output_tokens", "cost_usd")]
    for name in observation_metrics:
        metric = "smr_" + name + ("_sum" if name.endswith("duration_seconds") else "_total")
        queries[name] = (False, "sum(" + inc(metric) + ")")
    # Account balances include other tools. Never restrict them to routing
    # project/user/agent/instance or sum the same account's installed copies.
    account_selector = ',account=' + json.dumps(account) if account else ''
    # Preserve installation identity until selecting one coherent, freshest
    # successful snapshot per account and API scope; MAX of balances is unsafe.
    queries["account_values"] = (False, 'last_over_time({__name__=~"smr_openrouter_.*_usd"' + account_selector + '}[' + window + '])')
    queries["account_health"] = (False, 'last_over_time({__name__=~"smr_openrouter_.*_(balance_probe_success|last_success_timestamp_seconds|last_attempt_timestamp_seconds|limit_configured|limit_remaining_available|usage_daily_available|usage_weekly_available|usage_monthly_available)"' + account_selector + '}[' + window + '])')
    data, errors = {}, {}
    def fetch(item):
        name, (ranged, expression) = item
        params = {"query": expression, "timeout": str(config["timeout_seconds"]) + "s"}
        params.update({"start": start, "end": end, "step": step} if ranged else {"time": end})
        url = config["query_url"].rstrip("/") + ("/api/v1/query_range" if ranged else "/api/v1/query")
        try:
            rows = _decode(request(config, url + "?" + urllib.parse.urlencode(params)), ranged)
            return name, rows, None
        except Exception:
            return name, [], "query failed or returned invalid data"
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for name, rows, error in pool.map(fetch, queries.items()):
            data[name] = rows
            if error:
                errors[name] = error
    total = _total(data["calls"])
    requests = _total(data["requests"])
    failed_rows = [row for row in data["requests"] if row["labels"].get("outcome") != "success"]
    failed = _total(failed_rows) if failed_rows else (0.0 if requests is not None else None)
    applied_rows = [row for row in data["calls"] if row["labels"].get("applied") == "true"]
    shadow_rows = [row for row in data["calls"] if row["labels"].get("mode") == "shadow"]
    summary = {"calls": total, "jev_requests": requests, "jev_errors": failed,
               "error_share": failed / requests if requests and failed is not None else None,
               "applied": _total(applied_rows) if applied_rows else (0.0 if total is not None else None),
               "shadow": _total(shadow_rows) if shadow_rows else (0.0 if total is not None else None)}
    summary["hook_versions"] = hook_versions(data["hook_versions"], end)
    summary["hook_version_mixed_reporters"] = mixed_version_reporters(summary["hook_versions"])
    missing_metadata = [row for row in data["calls"] if not _reporter_labels(row["labels"])]
    summary["hook_version_metadata_gaps"] = _total(missing_metadata) if missing_metadata else (0 if total is not None else None)
    for key in ("jev", "hook"):
        for q in (50, 95, 99):
            summary[key + "_p" + str(q) + "_seconds"] = _percentile(data[key + "_buckets"], q / 100)
    for key in ("pending_events", "coalesced_events", "dropped_events"):
        summary[key] = _total(data[key])
    delivery = _total(data["last_delivery"])
    summary["last_delivery_age_seconds"] = max(0, end - delivery) if delivery and delivery > 0 else None
    for key in ("jev_cost_usd", "jev_known_cost_requests", "jev_unpriced_requests", "jev_cost_rate_current"):
        summary[key] = _total(data[key])
    known, unpriced = summary["jev_known_cost_requests"], summary["jev_unpriced_requests"]
    # Sparse counters: an absent category is zero only when its complementary
    # category is observed. With neither category observed, coverage is unknown.
    observed = (known or 0) + (unpriced or 0)
    summary["jev_cost_coverage"] = ((known or 0) / observed if observed else None) if not any(key in errors for key in ("jev_known_cost_requests", "jev_unpriced_requests")) else None
    summary["jev_cost_average_hour"] = summary["jev_cost_usd"] / (days * 24) if summary["jev_cost_usd"] is not None else None
    for name in observation_metrics:
        summary[name] = _total(data[name]) if all(_value(row) is not None and _value(row) >= 0 for row in data[name]) else None
    for direction in ("input", "output"):
        prefix = "jev_" + direction
        known_key, unknown_key = prefix + "_known_token_requests", prefix + "_unknown_token_requests"
        known, unknown = summary[known_key], summary[unknown_key]
        unavailable = any(key in errors or (data[key] and summary[key] is None) for key in (known_key, unknown_key))
        # Coverage counters started after the request/token counters. Include
        # older, unmeasured requests in the denominator instead of claiming
        # whole-window coverage from only post-upgrade observations.
        unavailable |= "requests" in errors or requests is None or requests < 0 or any(
            _value(row) is None or _value(row) < 0 for row in data["requests"])
        if not unavailable:
            unavailable = (known or 0) + (unknown or 0) > requests
        summary[prefix + "_token_coverage"] = (known or 0) / requests if not unavailable and requests else None
        summary[unknown_key] = requests - (known or 0) if not unavailable else None
    snapshots = {}
    for row in data["account_values"] + data["account_health"]:
        alias = row["labels"].get("account")
        instance = row["labels"].get("instance", "")
        metric = row["labels"].get("__name__", "")
        if alias and metric.startswith("smr_openrouter_"):
            snapshots.setdefault((alias, instance), {})[metric.removeprefix("smr_openrouter_")] = _value(row)
    accounts = {}
    for alias in sorted({key[0] for key in snapshots}):
        candidates = [(instance, values) for (name, instance), values in snapshots.items() if name == alias]
        selected = accounts.setdefault(alias, {})
        for scope in ("key", "account"):
            stamp = scope + "_last_success_timestamp_seconds"
            eligible = [(instance, values) for instance, values in candidates if values.get(stamp) is not None]
            if eligible:
                # Timestamp ties select the conservative smaller remaining
                # amount, then the installation alias for determinism.
                balance = scope + ("_balance_usd" if scope == "account" else "_limit_remaining_usd")
                instance, latest = min(eligible, key=lambda pair: (-pair[1][stamp], pair[1].get(balance) if pair[1].get(balance) is not None else math.inf, pair[0]))
                selected.update({key: value for key, value in latest.items() if key.startswith(scope + "_")})
            # Last probe status is a separate freshness stream, including a
            # failed newer attempt on a different installation.
            attempt = scope + "_last_attempt_timestamp_seconds"
            attempts = [(instance, values) for instance, values in candidates if values.get(attempt) is not None]
            if attempts:
                _, latest_probe = min(attempts, key=lambda pair: (-pair[1][attempt], pair[1].get(scope + "_balance_probe_success", 0), pair[0]))
                selected[scope + "_balance_probe_success"] = latest_probe.get(scope + "_balance_probe_success")
                selected[attempt] = latest_probe[attempt]
    for values in accounts.values():
        for field, marker in (("key_limit_usd", "key_limit_configured"), ("key_limit_remaining_usd", "key_limit_remaining_available"),
                              *(("key_usage_" + period + "_usd", "key_usage_" + period + "_available") for period in ("daily", "weekly", "monthly"))):
            if values.get(marker) != 1:
                values[field] = None
        for scope in ("key", "account"):
            stamp = values.get(scope + "_last_success_timestamp_seconds")
            values[scope + "_age_seconds"] = max(0, end - stamp) if stamp else None
    summary["accounts"] = accounts
    for label in ("model", "tier", "reason", "project", "user", "agent"):
        counts = {}
        for row in data["calls"]:
            if label in ("model", "tier") and not row["labels"].get("reason", "").startswith("rule:"):
                continue
            value = _value(row)
            if value is not None:
                name = row["labels"].get(label) or "unknown"
                counts[name] = counts.get(name, 0.0) + value
        summary["by_" + label] = counts
    has_data = any(point[1] is not None for name, rows in data.items()
                   if name not in ("pending_events", "coalesced_events", "dropped_events", "last_delivery", "account_values", "account_health", "hook_versions")
                   for row in rows for point in row["points"])
    status = ("partial" if len(errors) < len(queries) else "error") if errors else ("ok" if has_data else "no_data")
    return {"status": status, "instance": config["instance"], "project": project, "user": user, "agent": agent, "account": account, "start": start, "end": end,
            "step": step, "summary": summary, "series": data, "errors": errors,
            "note": "Window estimates from received counter samples. Gaps mean no samples; a stopped worker or delayed delivery can cause gaps. Telemetry health is the last received snapshot, not live state; coalesced/dropped are lifetime counters, last-success trails by one flush. Workers exit after five minutes per run; later calls restart them. Latencies include failures. Selection share is not cost or quality evidence."}


def _fmt(value, unit=""):
    if value is None:
        return "No data"
    if unit == "%":
        return f"{value * 100:.1f}%"
    if unit == "ms":
        return f"{value * 1000:,.0f} ms"
    if unit == "s":
        return f"{value:,.0f} s"
    if unit == "usd":
        return f"${value:,.6f}"
    return f"{value:,.1f}".removesuffix(".0")


def format_summary(data):
    source = "Local journal" if data.get("source") == "local" else "VictoriaMetrics"
    lines = [source + " routing statistics: " + data["status"],
             "Instance: " + data["instance"],
             "Project: " + (data.get("project") or "all"),
             "User: " + (data.get("user") or "all"),
             "Calls: " + _fmt(data["summary"]["calls"]),
             "Jev requests: " + _fmt(data["summary"]["jev_requests"]),
             "Jev error share: " + _fmt(data["summary"]["error_share"], "%")]
    for key in ("jev", "hook"):
        lines.append(key.capitalize() + " latency p50 / p95 / p99: " + " / ".join(
            _fmt(data["summary"][key + "_p" + str(q) + "_seconds"], "ms") for q in (50, 95, 99)))
    if data["errors"]:
        lines.append("Failed queries: " + ", ".join(sorted(data["errors"])))
    for title, key in (("Calls by user", "by_user"), ("Calls by project", "by_project"), ("Model selections", "by_model"), ("Routing reasons", "by_reason")):
        counts = data["summary"][key]
        lines.append(title + ": " + (", ".join(name + " " + _fmt(count) for name, count in
                     sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]) if counts else "No data"))
    lines.append("Telemetry last snapshot: pending " + _fmt(data["summary"]["pending_events"]) +
                 "; coalesced lifetime " + _fmt(data["summary"]["coalesced_events"]) +
                 "; dropped lifetime " + _fmt(data["summary"]["dropped_events"]) +
                 "; delivery age " + _fmt(data["summary"]["last_delivery_age_seconds"], "s"))
    lines.extend(title + ": " + value for title, value in money_rows(data["summary"]))
    lines.append(VERSION_NOTE)
    lines.append("Reporters with multiple observed versions: " + _fmt(data["summary"].get("hook_version_mixed_reporters")))
    lines.append("Calls with missing reporter metadata (routing filters): " + _fmt(data["summary"].get("hook_version_metadata_gaps")))
    for row in data["summary"].get("hook_versions", []):
        lines.append(" / ".join(row[key] for key in ("instance", "host", "user", "agent")) +
                     ": plugin=" + row["plugin_version"] + "; client=" + row["agent_version"] + "; " +
                     _fmt(row["age_seconds"], "s") + " ago; " + ("latest observed" if row["latest_observed"] else "historical"))
    lines.append(data["note"])
    return "\n".join(lines)


def money_rows(summary):
    """Small shared financial view: unknown prices and stale balances stay explicit."""
    rows = [("Jev reported spend · window", _fmt(summary.get("jev_cost_usd"), "usd")),
            ("Known cost coverage", _fmt(summary.get("jev_cost_coverage"), "%")),
            ("Unpriced requests", _fmt(summary.get("jev_unpriced_requests"))),
            ("Jev spend · recent USD/hour", _fmt(summary.get("jev_cost_rate_current"), "usd")),
            ("Jev spend · window average USD/hour", _fmt(summary.get("jev_cost_average_hour"), "usd"))]
    for direction in ("input", "output"):
        prefix = "jev_" + direction
        rows.extend([("Jev " + direction + " tokens · reported", _fmt(summary.get(prefix + "_tokens"))),
                     ("Jev " + direction + " token coverage", _fmt(summary.get(prefix + "_token_coverage"), "%")),
                     ("Jev requests without " + direction + " tokens", _fmt(summary.get(prefix + "_unknown_token_requests")))])
    for title, key, unit in (("observations", "requests", ""), ("local read attempts", "read_attempts", ""),
                             ("local bytes read", "bytes_read", ""), ("local duration · total", "duration_seconds", "ms"),
                             ("API input tokens", "api_input_tokens", ""), ("API output tokens", "api_output_tokens", ""),
                             ("API spend", "cost_usd", "usd")):
        rows.append(("Claude model lookup · " + title, _fmt(summary.get("claude_model_lookup_" + key), unit)))
    accounts = summary.get("accounts") or {}
    if not accounts:
        rows.append(("OpenRouter account / key snapshots", "No data"))
    for alias, values in sorted(accounts.items()):
        for label, key in (("Account credit balance", "account_balance_usd"), ("Key limit remaining", "key_limit_remaining_usd"), ("Key billed today", "key_usage_daily_usd"), ("Key billed this month", "key_usage_monthly_usd")):
            rows.append((alias + " · " + label, _fmt(values.get(key), "usd")))
        for scope in ("key", "account"):
            success = values.get(scope + "_balance_probe_success")
            state = "failed" if success == 0 else "success" if success == 1 else "No data"
            rows.append((alias + " · " + scope + " latest probe / snapshot age", state + " / " + _fmt(values.get(scope + "_age_seconds"), "s")))
    return rows


def _chart(rows, start, end, step):
    finite = [p[1] for row in rows for p in row["points"] if p[1] is not None]
    if not finite:
        return '<div class="empty">No samples in this window</div>'
    ceiling = max(max(finite), 0.001)
    parts = ['<svg viewBox="0 0 760 230" role="img" aria-label="Time series"><g fill="none" stroke="#263447">']
    for y in (25, 80, 135, 190):
        parts.append(f'<path d="M48 {y}H744"/>')
    parts.append('</g><g fill="#97a9be" font-size="11">')
    parts.append(f'<text x="2" y="28">{ceiling:.2g}</text><text x="20" y="193">0</text>')
    for x, timestamp in ((48, start), (636, end)):
        label = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%d %b %H:%M")
        parts.append(f'<text x="{x}" y="220">{label}</text>')
    parts.append('</g>')
    legend = []
    for index, row in enumerate(rows[:12]):
        color = COLORS[index % len(COLORS)]
        chunks, chunk, previous_timestamp = [], [], None
        for timestamp, value in row["points"]:
            if previous_timestamp is not None and timestamp - previous_timestamp > step * 1.5 and chunk:
                chunks.append(chunk)
                chunk = []
            previous_timestamp = timestamp
            if value is None:
                if chunk:
                    chunks.append(chunk)
                    chunk = []
                continue
            x = 48 + 696 * max(0, min(1, (timestamp - start) / max(1, end - start)))
            y = 190 - 165 * max(0, value) / ceiling
            chunk.append(f"{x:.1f},{y:.1f}")
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            parts.append(f'<polyline points="{" ".join(chunk)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
            if len(chunk) == 1:
                x, y = chunk[0].split(",")
                parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>')
        label = " · ".join(v for k, v in sorted(row["labels"].items()) if k != "__name__") or "p95"
        legend.append(f'<span><i style="background:{color}"></i>{html.escape(label)}</span>')
    return "".join(parts) + '</svg><div class="legend">' + "".join(legend) + "</div>"


def _breakdown(rows, label, decisions_only=False):
    totals = {}
    for row in rows:
        if decisions_only and not row["labels"].get("reason", "").startswith("rule:"):
            continue
        value = _value(row)
        if value is not None:
            name = row["labels"].get(label, "unknown")
            totals[name] = totals.get(name, 0) + value
    if not totals or sum(totals.values()) <= 0:
        return '<div class="empty">No selections in this window</div>'
    total = sum(totals.values())
    items = []
    for i, (name, count) in enumerate(sorted(totals.items(), key=lambda p: -p[1])[:20]):
        share = count / total * 100
        items.append(f'<div class="bar-label"><span>{html.escape(name)}</span><b>{_fmt(count)} · {share:.1f}%</b></div>'
                     f'<div class="track"><div style="width:{share:.2f}%;background:{COLORS[i % len(COLORS)]}"></div></div>')
    return "".join(items)


def html_document(data):
    """Build a standalone report containing escaped labels and no JavaScript."""
    esc = html.escape
    summary, series = data["summary"], data["series"]
    cards = [("Subagent calls", "calls", ""), ("Jev requests", "jev_requests", ""),
             ("Jev error share", "error_share", "%"), ("Applied routing", "applied", ""),
             ("Shadow calls", "shadow", ""), ("Jev p95", "jev_p95_seconds", "ms")]
    cards_html = "".join('<div class="card"><small>' + title + '</small><strong>' + _fmt(summary[key], unit) + '</strong></div>'
                         for title, key, unit in cards)
    panels = []
    for title, key, unit in (("Jev requests", "request_rate", "requests / second"),
                             ("Jev latency · p95", "latency_p95", "seconds · all outcomes"),
                             ("Model selections", "model_rate", "selections / second"),
                             ("Jev reported spend", "jev_cost_rate", "USD / hour · known costs only")):
        panels.append('<section><h2>' + title + '</h2><small>' + unit + '</small>' + _chart(series.get(key, []), data["start"], data["end"], data["step"]) + '</section>')
    panels.append('<section><h2>Reported costs and account snapshots</h2><p>Unpriced requests are not free. Token coverage is separate for input and output. Claude model lookup runs in local Python without an API call; API zeros apply only to recorded observations. Bytes are not tokens. Account and key totals include other tools; key limit remaining is not wallet credit. The freshest successful snapshot is selected across installations; values may be stale. Missing key limits can mean unlimited or unavailable.</p><table><tbody>' + ''.join('<tr><td>' + esc(title) + '</td><td>' + esc(value) + '</td></tr>' for title, value in money_rows(summary)) + '</tbody></table></section>')
    version_rows = []
    for row in summary.get("hook_versions", []):
        values = [row[key] for key in ("instance", "host", "user", "agent", "plugin_version", "agent_version")]
        values += [_fmt(row["age_seconds"], "s"), "latest observed" if row["latest_observed"] else "historical"]
        version_rows.append('<tr>' + ''.join('<td>' + esc(value) + '</td>' for value in values) + '</tr>')
    panels.append('<section><h2>Observed hook versions</h2><p>' + esc(VERSION_NOTE) + '</p><p>Reporters with multiple observed versions: ' +
                  _fmt(summary.get("hook_version_mixed_reporters")) + '</p><p>Calls with missing reporter metadata (routing filters): ' +
                  _fmt(summary.get("hook_version_metadata_gaps")) + '</p><table><thead><tr>' +
                  ''.join('<th>' + title + '</th>' for title in ("Instance", "Host", "User", "Client", "Plugin version", "Client version", "Last hook age", "Observation")) +
                  '</tr></thead><tbody>' + (''.join(version_rows) or '<tr><td colspan="8">No version observations</td></tr>') + '</tbody></table></section>')
    for title, label, decisions in (("Calls by user", "user", False), ("Calls by project", "project", False), ("Selection share by model", "model", True), ("Selection share by tier", "tier", True), ("Routing reasons", "reason", False)):
        panels.append('<section><h2>' + title + '</h2>' + _breakdown(series["calls"], label, decisions) + '</section>')
    health_html = '<section style="margin-top:18px"><h2>Telemetry delivery · last received snapshot</h2><p>Workers exit after five minutes per run; later calls restart them. Snapshot age alone does not prove a failure.</p><table><tbody>'
    for title, key, unit in (("Pending events", "pending_events", ""), ("Coalesced timing · lifetime", "coalesced_events", ""), ("Dropped events · lifetime", "dropped_events", ""), ("Last acknowledged delivery age", "last_delivery_age_seconds", "s")):
        health_html += '<tr><td>' + title + '</td><td>' + _fmt(summary[key], unit) + '</td></tr>'
    health_html += '</tbody></table></section>'
    latency_rows = "".join('<tr><td>' + name + '</td>' + "".join('<td>' + _fmt(summary[key + "_p" + str(q) + "_seconds"], "ms") + '</td>' for q in (50, 95, 99)) + '</tr>' for name, key in (("Jev · all outcomes", "jev"), ("Hook", "hook")))
    periods = [dt.datetime.fromtimestamp(data[key], dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") for key in ("start", "end")]
    error = ('<aside>Query failures: ' + esc(", ".join(sorted(data["errors"]))) + '. Missing results are unavailable.</aside>') if data["errors"] else ""
    document = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"><title>Subagent routing · Observability</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b111c;color:#e7eef8;font:14px system-ui,sans-serif}main{max-width:1440px;margin:auto;padding:40px 30px}header{border-bottom:1px solid #253144;margin-bottom:26px;padding-bottom:24px}.eyebrow{color:#73a7ff;letter-spacing:2px;font-size:11px;font-weight:700}h1{font-size:32px;margin:12px 0}h2{font-size:16px;margin:0 0 9px}p,small{color:#97a9be}p{line-height:1.6}.status{display:inline-block;border:1px solid #3b5677;border-radius:30px;padding:5px 13px;color:#9ec2ff}.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin:25px 0}.card,section{background:#121d2c;border:1px solid #263447;border-radius:12px}.card{padding:19px}.card strong{display:block;font-size:29px;margin-top:15px;font-weight:600}.panels{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}section{padding:22px;min-width:0}svg{display:block;width:100%;margin-top:16px}.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:11px;color:#b8c8dc}.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.bar-label{display:flex;justify-content:space-between;gap:15px;margin-top:19px;font-size:12px;overflow-wrap:anywhere}.bar-label b{white-space:nowrap;color:#97a9be;font-weight:400}.track{height:7px;background:#243145;border-radius:8px;margin-top:9px}.track div{height:7px;border-radius:8px}.empty{height:210px;display:grid;place-items:center;color:#97a9be}aside{background:#382627;color:#ffb7b7;padding:15px;border-radius:10px;margin-bottom:20px}table{border-collapse:collapse;width:100%;margin-top:16px}th,td{text-align:left;border-bottom:1px solid #263447;padding:13px}th{color:#97a9be;font-size:12px}footer{margin-top:24px;color:#8294ac;font-size:12px;line-height:1.7}@media(max-width:1000px){.cards{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){main{padding:22px 15px}.cards{grid-template-columns:repeat(2,1fr)}.panels{grid-template-columns:1fr}.card strong{font-size:24px}h1{font-size:26px}}@media print{body{background:white;color:#142235}.card,section{break-inside:avoid;background:white}.cards{grid-template-columns:repeat(3,1fr)}}
</style></head><body><main><header><div class="eyebrow">SUBAGENT MODEL ROUTER / OBSERVABILITY</div><h1>Routing operations</h1><p>''' + esc(data["instance"]) + ' · ' + esc(" → ".join(periods)) + '</p><span class="status">' + esc(data["status"].upper()) + '</span></header>' + error + '<div class="cards">' + cards_html + '</div><div class="panels">' + "".join(panels) + '</div><section style="margin-top:18px"><h2>Latency distribution</h2><table><thead><tr><th>Operation</th><th>p50</th><th>p95</th><th>p99</th></tr></thead><tbody>' + latency_rows + '</tbody></table></section><footer>' + esc(data["note"]) + ' This static report contains no credentials, remote resources, or executable scripts.</footer></main></body></html>'
    document = document.replace('<footer>', health_html + '<footer>', 1)
    document = document.replace('<h1>Routing operations</h1>', '<h1>Routing operations</h1><p>Project: ' + esc(data.get("project") or "all") + ' · User: ' + esc(data.get("user") or "all") + ' · Agent: ' + esc(data.get("agent") or "all") + ' · Source: ' + esc(data.get("source") or "victoriametrics") + '</p>', 1)
    return document


def render_html(data, path):
    """Explicitly export a standalone report to a private file."""
    document = html_document(data)
    target = Path(path).expanduser()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(document)
    return str(target)
