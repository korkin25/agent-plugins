"""Local, approximate visible-task token and input-price estimates.

The host's system prompt, tool wrappers, and future output are unavailable here.
This module never treats a local estimate as billed API usage.
"""
from __future__ import annotations

import math

MILLION = 1_000_000
METHOD = "utf8_bytes_div4_heuristic"
SCOPE = "filtered_subagent_task_and_description"
NATIVE_PROMPT_REASON = "host_system_tool_wrappers_and_future_output_not_visible"


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def estimated_request(state):
    """Describe the locally visible, filtered task size without tokenizing a host prompt."""
    if not isinstance(state, dict):
        return None
    description, task = state.get("description"), state.get("task")
    if not isinstance(description, str) or not isinstance(task, str):
        return None
    text = description + task
    byte_count = len(text.encode("utf-8"))
    return {
        "visible_task": {
            "scope": SCOPE,
            "characters": len(text),
            "utf8_bytes": byte_count,
            "input_tokens_estimate": (byte_count + 3) // 4,
            "method": METHOD,
            "approximate": True,
        },
        "native_child_prompt": {
            "status": "unknown",
            "reason": NATIVE_PROMPT_REASON,
        },
    }


def _cost(tokens, rate):
    return tokens * rate / MILLION if _number(tokens) and _number(rate) else None


def estimate_input_cost(request_estimate, price_reference):
    """Estimate uncached input USD for one exact fresh/stale API price reference."""
    visible = request_estimate.get("visible_task") if isinstance(request_estimate, dict) else None
    tokens = visible.get("input_tokens_estimate") if isinstance(visible, dict) else None
    price = price_reference if isinstance(price_reference, dict) else {}
    status = price.get("status")
    result = {
        "basis": "standard_api",
        "price_status": status if status in ("fresh", "stale") else "unknown",
        "price_retrieved_at": price.get("retrieved_at") if status in ("fresh", "stale") else None,
        "price_source_url": price.get("source_url") if status in ("fresh", "stale") else None,
        "unit": "USD",
        "input_tokens_estimate": tokens if _number(tokens) else None,
        "method": visible.get("method") if isinstance(visible, dict) else None,
        "approximate": True,
        "cache_assumption": "uncached_input",
        "context_band": "unknown",
        "uncached_input_usd_estimate": None,
        "long_context_uncached_input_usd_estimate": None,
    }
    if status not in ("fresh", "stale") or not _number(tokens):
        return result
    result["uncached_input_usd_estimate"] = _cost(tokens, price.get("input"))
    long_context = price.get("long_context")
    if isinstance(long_context, dict):
        result["long_context_uncached_input_usd_estimate"] = _cost(tokens, long_context.get("input"))
    return result
