"""Compact, safe terminal rendering for router statistics.

The renderer deliberately emits plain Markdown and Unicode only: it is suitable
for pasting into an agent response and does not require a terminal or HTML.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from collections import Counter

_BARS = "▏▎▍▌▋▊▉█"
_SPARK = "▁▂▃▄▅▆▇█"
_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}\Z")
_PROJECT_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")


def _clean(value, fallback="unknown"):
    value = str(value if value not in (None, "") else fallback)
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = value.translate(str.maketrans({"`": "'", "|": "¦", "[": "(", "]": ")", "<": "‹", ">": "›", "*": "·", "\\": "/"}))
    return " ".join(value.split())[:120]


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _observed_number(value, integer=False, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = _num(value)
    if number is None or number < 0 or (integer and not number.is_integer()) or (maximum is not None and number > maximum):
        return None
    return number


def _lookup_observation(value):
    if not isinstance(value, dict) or value.get("outcome") not in ("resolved", "not_found", "rejected"):
        return None
    for key, integer, maximum in (("read_attempts", True, 2), ("bytes_read", True, 2097152),
                                   ("duration_ms", False, None), ("api_input_tokens", True, 0),
                                   ("api_output_tokens", True, 0), ("cost_usd", False, 0)):
        if _observed_number(value.get(key), integer, maximum) is None:
            return None
    return value


def _fmt(value, suffix=""):
    if value is None:
        return "нет данных"
    if suffix == "%":
        return f"{value * 100:.1f}%"
    if suffix == "ms":
        return f"{value * 1000:,.0f} мс"
    if suffix == "usd":
        return f"${value:,.6f}"
    if abs(value - round(value)) < .01:
        return f"{value:,.0f}" + suffix
    return f"{value:,.1f}" + suffix


def _bar(value, maximum, width=18):
    if maximum <= 0 or value is None:
        return "░" * width
    filled = max(0, min(width, round(width * value / maximum)))
    return "█" * filled + "░" * (width - filled)


def _spark(points, width=32):
    vals = [(_num(p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else None) for p in points]
    if not any(v is not None for v in vals):
        return "нет данных"
    if len(vals) > width:
        buckets = [vals[int(i * len(vals) / width):int((i + 1) * len(vals) / width)] for i in range(width)]
        vals = [sum(bucket) / len(bucket) if bucket and all(v is not None for v in bucket) else None for bucket in buckets]
        if not any(v is not None for v in vals):
            return "·" * len(vals)
    finite = [v for v in vals if v is not None]
    lo, hi = min(finite), max(finite)
    return "".join("·" if v is None else _SPARK[0 if hi == lo else min(7, int((v-lo)/(hi-lo)*7))] for v in vals)


def local_data(rows, days=None, now=None, project=None, user=None, agent=None):
    """Adapt journal rows to the dashboard shape without deriving private metadata."""
    rows = [r for r in rows if isinstance(r, dict)]
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days) if days is not None else None
    rows = [r for r in rows if (stamp := _parse_time(r.get("ts"))) is not None
            and stamp <= now and (cutoff is None or stamp >= cutoff)]
    projects = {}
    # Journal rows carry cwd rather than a resolved cohort. One project per row
    # keeps the project filter, breakdowns and hook-version rows consistent.
    rows = [dict(r, project=_local_project(r, projects)) for r in rows]
    rows = [r for r in rows if all(want is None or r.get(key) == want
                                  for key, want in (("user", user), ("agent", agent)))]
    rows = [r for r in rows if project is None or r.get("project") == project]
    version_rows = rows
    end = now.timestamp()
    start = (cutoff or min((_parse_time(r.get("ts")) for r in version_rows), default=now)).timestamp()
    decisions = [r for r in rows if _is_direct_choice(r)]
    attempted = [r for r in rows if _jev_attempted(r)]
    errors = sum(_jev_outcome(r) != "success" for r in attempted)
    summary = {"calls": len(rows) if rows else None,
               "jev_requests": len(attempted) if rows else None,
               "jev_errors": errors if attempted else None,
               "applied": sum(r.get("mode") == "active" and _changed(r) for r in decisions) if rows else None,
               "shadow": sum(r.get("mode") == "shadow" for r in rows) if rows else None,
               "error_share": errors / len(attempted) if attempted else None}
    from router_dashboard import hook_versions, mixed_version_reporters, _reporter_labels
    summary["hook_versions"] = hook_versions([
        {"labels": dict({key: r.get(key) for key in ("host", "user", "agent", "project", "plugin_version", "agent_version")}, instance="local journal"),
         "points": [[end, _parse_time(r["ts"]).timestamp()]]} for r in version_rows], end)
    summary["hook_version_mixed_reporters"] = mixed_version_reporters(summary["hook_versions"])
    summary["hook_version_metadata_gaps"] = sum(not _reporter_labels(r) for r in rows) if rows else None
    summary.update({"jev_p" + str(q) + "_seconds": _percentile([_num(r.get("latency_ms")) for r in attempted], q)
                    for q in (50, 95, 99)})
    summary.update({"hook_p" + str(q) + "_seconds": None for q in (50, 95, 99)})
    for label in ("recommended_model", "recommended_effort", "model", "effort", "reason", "project", "user", "agent"):
        summary["by_" + label] = dict(Counter(_clean(_journal_label(r, label)) for r in rows
                                            if (not label.startswith("recommended_") or _is_direct_choice(r))
                                            and (label not in ("model", "effort") or _is_current_record(r))))
    summary["models_by_project"] = _project_counts((r["project"], _launched_model(r)) for r in rows)
    summary["recommended_by_project"] = _project_counts((r["project"], _journal_label(r, "recommended_model")) for r in rows)
    summary["policy"] = _local_policy(rows)
    summary.update({key: None for key in ("pending_events", "coalesced_events", "dropped_events", "last_delivery_age_seconds")})
    costs = [value for r in attempted if isinstance(r.get("usage"), dict)
             and isinstance(r["usage"].get("cost"), (int, float))
             and not isinstance(r["usage"].get("cost"), bool)
             and (value := _num(r["usage"].get("cost"))) is not None and value >= 0]
    span_hours = (end - start) / 3600
    summary.update(jev_cost_usd=sum(costs) if costs else None,
                   jev_known_cost_requests=len(costs) if attempted else None,
                   jev_unpriced_requests=len(attempted) - len(costs) if attempted else None,
                   jev_cost_coverage=len(costs) / len(attempted) if attempted else None,
                   jev_cost_average_hour=sum(costs) / span_hours if costs and span_hours > 0 else None,
                   jev_cost_rate_current=None, accounts={})
    for direction in ("input", "output"):
        prefix = "jev_" + direction
        tokens = [value for r in attempted if isinstance(r.get("usage"), dict)
                  and (value := _observed_number(r["usage"].get(direction + "_tokens"), integer=True)) is not None]
        summary.update({prefix + "_tokens": sum(tokens) if tokens else None,
                        prefix + "_known_token_requests": len(tokens) if attempted else None,
                        prefix + "_unknown_token_requests": len(attempted) - len(tokens) if attempted else None,
                        prefix + "_token_coverage": len(tokens) / len(attempted) if attempted else None})
    lookups = [value for r in rows if (value := _lookup_observation(r.get("claude_model_lookup"))) is not None]
    summary["claude_model_lookup_requests"] = len(lookups) if lookups else None
    for key in ("read_attempts", "bytes_read", "api_input_tokens", "api_output_tokens", "cost_usd"):
        summary["claude_model_lookup_" + key] = sum(r[key] for r in lookups) if lookups else None
    summary["claude_model_lookup_duration_seconds"] = sum(r["duration_ms"] for r in lookups) / 1000 if lookups else None
    calls = [{"labels": {k: str(_journal_label(r, k) or "unknown") for k in ("recommended_model", "recommended_effort", "model", "effort", "reason", "project", "user", "agent")}
              | {"record_schema": "direct" if _is_current_record(r) else "legacy"},
              "points": [[_parse_time(r["ts"]).timestamp(), 1]]} for r in rows]
    return {"status": "ok" if rows else "no_data", "source": "local", "instance": "local journal", "project": project, "user": user,
            "agent": agent, "start": start, "end": end, "step": 0, "summary": summary,
            "series": {"calls": calls, "request_rate": [], "model_rate": [], "latency_p95": []}, "errors": {},
            "note": "Точные наблюдения локального журнала; отсутствующие поля не восстанавливаются."}


def _local_project(row, cache):
    """Recorded cohort, else the project resolved from the journal's cwd, else unknown."""
    value = row.get("project")
    if isinstance(value, str) and _PROJECT_RE.fullmatch(value):
        return value
    cwd = row.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return "unknown"
    if cwd not in cache:
        from router_telemetry import resolve_project
        cache[cwd] = resolve_project(cwd, {})
    return cache[cwd]


def _launched_model(row):
    """Submitted launch model under the same evidence rules as the exported calls counter."""
    value = row.get("actual_model")
    if not isinstance(value, str) or not _MODEL_ID_RE.fullmatch(value):
        return None
    reason = row.get("reason")
    exact = (reason in ("choice", "policy") and row.get("jev_attempted") is True
             and row.get("jev_outcome") == "success" and row.get("applied") is True and value == row.get("model"))
    explicit = reason == "explicit" and row.get("model_source") == "specified"
    return value if exact or explicit else None


def _project_counts(pairs):
    counts = Counter((project, model) for project, model in pairs if model)
    return [{"project": project, "model": model, "calls": calls}
            for (project, model), calls in sorted(counts.items(), key=lambda item: (item[0][0], -item[1], item[0][1]))]


def _rate(value):
    return _observed_number(value)


def _local_policy(rows):
    """Factor policy from journal fields, mirroring the exported policy counters."""
    from router_dashboard import POLICY_ADJUSTMENTS, PRICE_SOURCES, policy_summary
    outcome, agreement, level, model, adjustments = Counter(), Counter(), Counter(), Counter(), Counter()
    for r in rows:
        policy = r.get("policy")
        if not isinstance(policy, dict) or not _jev_attempted(r):
            continue
        raw = policy.get("outcome")
        result = "success" if raw == "success" else str(raw).removeprefix("error:")
        result = result if result in ("success", "answers", "range", "options", "sum") else "unknown"
        success = result == "success"
        outcome[result] += 1
        value = policy.get("agreement")
        agreement[value if value in ("identical", "same_model", "other_model", "policy_higher", "policy_lower") else "unknown"] += 1
        value = policy.get("level")
        level[str(value) if success and not isinstance(value, bool) and value in (1, 2, 3, 4) else "none"] += 1
        value = policy.get("model")
        model[(value if isinstance(value, str) and _MODEL_ID_RE.fullmatch(value) else "unknown")
              if success and value else "none"] += 1
        if success:
            for name in policy.get("adjustments") or ():
                name = str(name).replace(":", "_")
                if name in POLICY_ADJUSTMENTS:
                    adjustments[name] += 1
    totals, priced = {}, {}
    for r in rows:
        policy = r.get("policy") if isinstance(r.get("policy"), dict) else {}
        for source in PRICE_SOURCES:
            value = _rate(policy.get("output_rate") if source == "policy" else r.get(source + "_output_rate"))
            if value is not None:
                totals[source] = totals.get(source, 0) + value
                priced[source] = priced.get(source, 0) + 1
    return policy_summary(dict(outcome), dict(agreement), dict(level), dict(model), dict(adjustments), totals, priced)


def _parse_time(value):
    if not isinstance(value, str): return None
    try: return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError: return None


def _changed(row):
    return row.get("applied") is True


def _is_choice(reason):
    return reason == "choice" or str(reason or "").startswith("rule:")


def _is_current_record(row):
    return isinstance(row.get("jev_attempted"), bool)


def _is_direct_choice(row):
    return row.get("reason") in ("choice", "policy") and row.get("jev_attempted") is True


def _is_successful_direct_choice(row):
    return _is_direct_choice(row) and row.get("jev_outcome") == "success"


def _jev_attempted(row):
    if _is_current_record(row):
        return row["jev_attempted"] is True
    return _num(row.get("latency_ms")) is not None


def _jev_outcome(row):
    if _is_current_record(row):
        value = row.get("jev_outcome")
        if value == "success":
            return "success"
        return value.removeprefix("error:") if isinstance(value, str) and value.startswith("error:") else "unknown"
    return str(row.get("reason", "")).removeprefix("error:") if str(row.get("reason", "")).startswith("error:") else "success"


def _journal_label(row, label):
    """Map journal's core fields to the same selected/submitted contract as VM."""
    source = "choice_" if row.get("reason") == "policy" else ""  # Jev's Choice, even when the policy launched
    if label == "recommended_model":
        value = row.get(label, row.get(source + "model") if _is_successful_direct_choice(row) else None)
        return value if isinstance(value, str) and _MODEL_ID_RE.fullmatch(value) and _is_successful_direct_choice(row) else None
    if label == "recommended_effort":
        value = row.get(label, row.get(source + "effort") if _is_direct_choice(row) else None)
        return "not_supported" if (value is None and _is_successful_direct_choice(row)
                                    and row.get("selected_effort_supported") is False) else value
    if label == "model":
        value = row.get("actual_model")
        exact = (_is_successful_direct_choice(row) and row.get("applied") is True
                 and value == row.get("model"))
        return value if exact and isinstance(value, str) and _MODEL_ID_RE.fullmatch(value) else None
    if label == "effort":
        value = row.get("actual_effort")
        exact = (_is_successful_direct_choice(row) and row.get("applied") is True
                 and row.get("actual_model") == row.get("model"))
        if value is None and "actual_effort" in row:
            return "not_supported" if exact and row.get("selected_effort_supported") is False else "not_set"
        return value if exact else None
    return row.get(label)


def _percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values: return None
    return values[min(len(values)-1, max(0, math.ceil(q / 100 * len(values)) - 1))] / 1000


def format_terminal(data):
    """Return one compact Russian Markdown dashboard, safe for untrusted labels."""
    status = _clean(data.get("status", "unknown")); summary = data.get("summary") or {}
    source = _clean(data.get("source", "victoriametrics"))
    start = _date(data.get("start")); end = _date(data.get("end"))
    lines = [f"**Статистика маршрутизации · {status}**", f"Окно: {start} — {end} UTC · источник: {source} · instance: {_clean(data.get('instance'))}", f"Клиент: {_clean(data.get('agent'), 'все')} · фильтры: project={_clean(data.get('project'), 'все')} · user={_clean(data.get('user'), 'все')}", "", "| Метрика | Значение |", "|---|---:|", f"| Вызовы (оценка) | {_fmt(_num(summary.get('calls')))} |", f"| Jev-запросы | {_fmt(_num(summary.get('jev_requests')))} |", f"| Ошибки Jev | {_fmt(_num(summary.get('error_share')), '%')} |", f"| Latency p50 / p95 / p99 | {_fmt(_num(summary.get('jev_p50_seconds')), 'ms')} / {_fmt(_num(summary.get('jev_p95_seconds')), 'ms')} / {_fmt(_num(summary.get('jev_p99_seconds')), 'ms')} |", ""]
    lines.extend([f"**Расходы Jev за окно:** {_fmt(summary.get('jev_cost_usd'), 'usd')} · покрытие ценой {_fmt(summary.get('jev_cost_coverage'), '%')} · без цены {_fmt(summary.get('jev_unpriced_requests'))}.",
                  f"USD/час: {_fmt(summary.get('jev_cost_rate_current'), 'usd')} сейчас · {_fmt(summary.get('jev_cost_average_hour'), 'usd')} в среднем за окно."])
    for direction, title in (("input", "вход"), ("output", "выход")):
        prefix = "jev_" + direction
        lines.append(f"Токены Jev ({title}): {_fmt(summary.get(prefix + '_tokens'))} · покрытие {_fmt(summary.get(prefix + '_token_coverage'), '%')} · без данных {_fmt(summary.get(prefix + '_unknown_token_requests'))} запросов.")
    if not summary.get('accounts'):
        lines.append("Баланс OpenRouter и остаток лимита ключа: нет данных.")
    for alias, values in sorted((summary.get('accounts') or {}).items()):
        lines.append(f"**{_clean(alias)}:** баланс {_fmt(values.get('account_balance_usd'), 'usd')} · остаток лимита ключа {_fmt(values.get('key_limit_remaining_usd'), 'usd')} · ключ за месяц {_fmt(values.get('key_usage_monthly_usd'), 'usd')}.")
        for scope, title in (("key", "ключ"), ("account", "аккаунт")):
            success = values.get(scope + '_balance_probe_success')
            state = "ошибка" if success == 0 else "успех" if success == 1 else "нет данных"
            lines.append(f"Последняя проверка ({title}): {state}; возраст снимка {_fmt(values.get(scope + '_age_seconds'))} с.")
    lines.extend(["Учтены только сообщённые цены; неизвестная цена не равна нулю. Баланс и лимит — последние снимки; суммы аккаунта включают другие инструменты. Лимит ключа не равен кредитному балансу.", ""])
    lines.extend(["**Наблюдавшиеся версии hook**", "",
                  "Область: instance/user/клиент и фильтр project, если он задан; колонка «Проект» — проект, о котором сообщил hook (у рядов старых версий без этой метки — unknown). Последняя — по времени hook, а не по номеру релиза. Это не список установленных версий; неактивные и неотчитавшиеся установки неизвестны.",
                  "Версии плагина и вызвавшего hook клиента Claude Code/Codex показаны отдельно от модели; отсутствующая версия клиента неизвестна.",
                  "Reporter с несколькими наблюдавшимися версиями: " + _fmt(summary.get("hook_version_mixed_reporters")) + ".",
                  "Вызовы без метаданных reporter (фильтры маршрутизации): " + _fmt(summary.get("hook_version_metadata_gaps")) + ".", "",
                  "| Instance / host / user / клиент | Проект | Плагин | Версия клиента | Возраст hook | Наблюдение |", "|---|---|---|---|---:|---|"])
    for row in summary.get("hook_versions", []):
        reporter = " / ".join(_clean(row.get(key)) for key in ("instance", "host", "user", "agent"))
        state = "последняя наблюдавшаяся" if row["latest_observed"] else "историческая"
        lines.append(f"| {reporter} | {_clean(row.get('project'))} | {_clean(row.get('plugin_version'))} | {_clean(row.get('agent_version'))} | {_fmt(row.get('age_seconds'))} с | {state} |")
    if not summary.get("hook_versions"):
        lines.append("| нет наблюдений версий | неизвестно | неизвестно | неизвестно | нет данных | неизвестно |")
    lines.append("")
    lines.extend(_terminal_models(summary))
    lines.extend(_terminal_policy(summary))
    for title, key in (("Выбор Jev: модели", "by_recommended_model"), ("Выбор Jev: effort", "by_recommended_effort"), ("Переданные модели", "by_model"), ("Переданный effort", "by_effort"), ("Проекты", "by_project"), ("Пользователи", "by_user"), ("Агенты", "by_agent"), ("Причины", "by_reason")):
        values = data.get("summary", {}).get(key, {}) or {}
        lines.append(f"**{title}**")
        lines.append("")
        if not values: lines.append("нет данных")
        else:
            maximum = max(values.values())
            for name, count in sorted(values.items(), key=lambda x: (-x[1], x[0]))[:8]: lines.append(f"{_clean(name)}  {_bar(count, maximum)}  {_fmt(count)}  ")
        lines.append("")
    for key, title in (("request_rate", "Тренд запросов"), ("model_rate", "Тренд выборов моделей")):
        rows = (data.get("series") or {}).get(key, [])
        for row in rows[:4]:
            points = row.get("points", [])
            step = data.get("step", 0)
            expanded = []
            for point in points:
                if step and expanded and point[0] - expanded[-1][0] > step * 1.5:
                    expanded.append([point[0] - step, None])
                expanded.append(point)
            label = ", ".join(_clean(v) for v in row.get("labels", {}).values()) or "ряд"
            lines.append(f"**{title} · {label}** `{_spark(expanded)}`")
    if data.get("errors"): lines.extend(["", "⚠ Частичный результат: недоступно " + ", ".join(_clean(k) for k in sorted(data["errors"]))])
    if status == "no_data": lines.extend(["", "Данных маршрутизации в выбранном окне нет; нулевые значения не подставлены."])
    lines.extend(["", "Локальный журнал: наблюдения; квантили по измеренным запросам." if source == "local" else
                  "VictoriaMetrics: оценки по полученным счётчикам; пропуски — не нули. Доля выбора не доказывает экономию."])
    return "\n".join(lines).rstrip() + "\n"


def _terminal_models(summary):
    launched, recommended = summary.get("models_by_project"), summary.get("recommended_by_project")
    cells = {}
    for index, rows in enumerate((launched, recommended)):
        for row in rows or ():
            cells.setdefault((row.get("project"), row.get("model")), [None, None])[index] = _num(row.get("calls"))
    def cell(value, source):
        return _fmt(value) if value is not None else ("нет данных" if source is None else "—")
    lines = ["**Модели по проектам**", "",
             "Запущено — переданная при запуске модель (выбор Jev или применённая политика, либо указанная явно); рекомендовал Jev — прямой выбор Jev. «—» — не наблюдалось.", "",
             "| Проект | Модель | Запущено | Рекомендовал Jev |", "|---|---|---:|---:|"]
    for (project, model), (first, second) in sorted(cells.items(), key=lambda item: (str(item[0][0]), -sum(v or 0 for v in item[1]), str(item[0][1])))[:40]:
        lines.append(f"| {_clean(project)} | {_clean(model)} | {cell(first, launched)} | {cell(second, recommended)} |")
    if not cells:
        lines.append("| нет данных | нет данных | нет данных | нет данных |")
    return lines + [""]


def _counts_line(counts, names=None):
    if counts is None:
        return "нет данных"
    if not counts:
        return "не наблюдалось"
    return " · ".join(_clean((names or {}).get(name, name)) + " " + _fmt(_num(count))
                      for name, count in sorted(counts.items(), key=lambda item: (-(_num(item[1]) or 0), str(item[0])))[:10])


def _terminal_policy(summary):
    policy = summary.get("policy") or {}
    levels = {"1": "1 (лёгкий)", "2": "2 (стандартный)", "3": "3 (сильный)", "4": "4 (frontier)"}
    lines = ["**Факторная политика**", "",
             f"Решений за окно: {_fmt(_num(policy.get('decisions')))} · ошибки исхода: {_fmt(_num(policy.get('outcome_errors')))} ({_fmt(_num(policy.get('outcome_error_share')), '%')}).",
             "Согласие с выбором Jev: " + _counts_line(policy.get("by_agreement")) + ".",
             "Уровни: " + _counts_line(policy.get("by_level"), levels) + ".",
             "Модели политики: " + _counts_line(policy.get("by_model")) + ".",
             "Корректировки: " + _fmt(_num(policy.get("adjustments_total"))) + (
                 " · " + _counts_line(policy.get("adjustments")) if policy.get("adjustments") else "") + "."]
    average = policy.get("average_output_usd_per_mtok") or {}
    priced = policy.get("priced_calls") or {}
    parts = []
    for source, title in (("choice", "выбор Jev"), ("policy", "политика"), ("selected", "выбранная к запуску")):
        value = _num(average.get(source))
        parts.append(f"{title} " + ("нет данных" if value is None else f"${value:,.3f}/Mtok ({_fmt(_num(priced.get(source)))} выз.)"))
    lines.append("Средняя цена выхода за вызов: " + " · ".join(parts) + ".")
    lines.append("policy_higher — политика хотела более сильную модель, чем выбрал Jev; policy_lower — выбор Jev дороже, чем политика сочла нужным. Цена — стандартный прайс API, экономический индикатор, не счёт.")
    return lines + [""]


def _date(value):
    try: return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError): return "нет данных"
