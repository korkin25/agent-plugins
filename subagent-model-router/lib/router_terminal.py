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


def _clean(value, fallback="unknown"):
    value = str(value if value not in (None, "") else fallback)
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = value.translate(str.maketrans({"`": "'", "|": "¦", "[": "(", "]": ")", "<": "‹", ">": "›", "*": "·", "\\": "/"}))
    return " ".join(value.split())[:120]


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


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
    rows = [r for r in rows if all(want is None or r.get(key) == want
                                  for key, want in (("project", project), ("user", user), ("agent", agent)))]
    end = now.timestamp()
    start = (cutoff or min((_parse_time(r.get("ts")) for r in rows), default=now)).timestamp()
    decisions = [r for r in rows if str(r.get("reason", "")).startswith("rule:")]
    attempted = [r for r in rows if r.get("state_sha256") or _num(r.get("latency_ms")) is not None
                 or str(r.get("reason", "")).startswith("rule:")]
    errors = sum(str(r.get("reason", "")).startswith("error:") for r in attempted)
    summary = {"calls": len(rows) if rows else None,
               "jev_requests": len(attempted) if rows else None,
               "jev_errors": errors if attempted else None,
               "applied": sum(r.get("mode") == "active" and _changed(r) for r in decisions) if rows else None,
               "shadow": sum(r.get("mode") == "shadow" for r in rows) if rows else None,
               "error_share": errors / len(attempted) if attempted else None}
    summary.update({"jev_p" + str(q) + "_seconds": _percentile([_num(r.get("latency_ms")) for r in attempted], q)
                    for q in (50, 95, 99)})
    summary.update({"hook_p" + str(q) + "_seconds": None for q in (50, 95, 99)})
    for label in ("model", "tier", "reason", "project", "user", "agent"):
        summary["by_" + label] = dict(Counter(_clean(r.get(label)) for r in rows if label not in ("model", "tier") or str(r.get("reason", "")).startswith("rule:")))
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
    calls = [{"labels": {k: str(r.get(k) or "unknown") for k in ("model", "tier", "reason", "project", "user", "agent")},
              "points": [[_parse_time(r["ts"]).timestamp(), 1]]} for r in rows]
    return {"status": "ok" if rows else "no_data", "source": "local", "instance": "local journal", "project": project, "user": user,
            "agent": agent, "start": start, "end": end, "step": 0, "summary": summary,
            "series": {"calls": calls, "request_rate": [], "model_rate": [], "latency_p95": []}, "errors": {},
            "note": "Точные наблюдения локального журнала; отсутствующие поля не восстанавливаются."}


def _parse_time(value):
    if not isinstance(value, str): return None
    try: return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError: return None


def _changed(row):
    vals = (row.get("model"), row.get("effort")) if row.get("agent") == "codex" else (row.get("model"),)
    return any(v not in (None, "inherit") for v in vals)


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
    if not summary.get('accounts'):
        lines.append("Баланс OpenRouter и остаток лимита ключа: нет данных.")
    for alias, values in sorted((summary.get('accounts') or {}).items()):
        lines.append(f"**{_clean(alias)}:** баланс {_fmt(values.get('account_balance_usd'), 'usd')} · остаток лимита ключа {_fmt(values.get('key_limit_remaining_usd'), 'usd')} · ключ за месяц {_fmt(values.get('key_usage_monthly_usd'), 'usd')}.")
        for scope, title in (("key", "ключ"), ("account", "аккаунт")):
            success = values.get(scope + '_balance_probe_success')
            state = "ошибка" if success == 0 else "успех" if success == 1 else "нет данных"
            lines.append(f"Последняя проверка ({title}): {state}; возраст снимка {_fmt(values.get(scope + '_age_seconds'))} с.")
    lines.extend(["Учтены только сообщённые цены; неизвестная цена не равна нулю. Баланс и лимит — последние снимки; суммы аккаунта включают другие инструменты. Лимит ключа не равен кредитному балансу.", ""])
    for title, key in (("Модели", "by_model"), ("Проекты", "by_project"), ("Пользователи", "by_user"), ("Агенты", "by_agent"), ("Причины", "by_reason")):
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
    if status == "no_data": lines.extend(["", "Данных в выбранном окне нет; нулевые значения не подставлены."])
    lines.extend(["", "Локальный журнал: наблюдения; квантили по измеренным запросам." if source == "local" else
                  "VictoriaMetrics: оценки по полученным счётчикам; пропуски — не нули. Доля выбора не доказывает экономию."])
    return "\n".join(lines).rstrip() + "\n"


def _date(value):
    try: return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError): return "нет данных"
