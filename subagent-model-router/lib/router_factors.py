"""Factor policy: Jev rates atomic task properties, code turns them into a launch pair.

Jev answers narrow Score/Noul questions about the task only; prices, catalogues
and model names never reach it (arithmetic and ranking stay in code, as the
TypeSafe docs recommend). The same request also carries the direct Choice, so
the factor recommendation costs no extra call and can be compared with it.
"""
from __future__ import annotations

import math

POLICY = "factors_v1"
PREFIX = "f_"
LEVELS = (1, 2, 3, 4)  # 1 light, 2 standard, 3 strong, 4 frontier
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

# Every Score describes situations, one dimension per question; wording is
# English because it is Jev's primary language. Keys are for code only.
QUESTIONS = {
    "reasoning": {"type": "score",
        "instructions": "What kind of thinking does the task require from the agent?",
        "criteria": [
            "Lookup, listing, quoting, reformatting, translation or a mechanical edit",
            "Ordinary implementation or comparison under a stated specification",
            "Diagnosing an unknown cause, or choosing a design among tradeoffs",
            "Reasoning about security, concurrency, data integrity or contracts between systems"]},
    "spec": {"type": "score",
        "instructions": "How completely does the task specify what to do?",
        "criteria": [
            "Only the goal is stated; method, files and acceptance are left to the agent",
            "Goal and approach are stated; details are left to the agent",
            "Exact steps, target files and expected result are stated"]},
    "verification": {"type": "score",
        "instructions": "How would a wrong result of this task be caught?",
        "criteria": [
            "Only by a person carefully reading the work",
            "Partly by stated checks and partly by judgment",
            "By stated automated checks or an exact expected output"]},
    "scope": {"type": "score",
        "instructions": "How much of the codebase or system does the task touch?",
        "criteria": [
            "One file or one small item",
            "Several files in one component",
            "Several components or the whole repository"]},
    "impact": {"type": "score",
        "instructions": "What happens if the agent gets this task wrong?",
        "criteria": [
            "Harmless and easy to redo",
            "Wasted time, but the damage stays local",
            "Data loss, broken shared systems, leaked secrets or messages reaching people outside"]},
    "review": {"type": "noul",
        "instructions": "Does the task ask the agent to judge finished work against requirements and "
                        "recommend approval or rejection?",
        "criteria": {
            "true": "An acceptance decision on someone else's finished work is requested",
            "false": "Doing the work itself, or reading or summarizing a document, including one named "
                     "'review', without an acceptance decision"}},
    "review_depth": {"type": "score",
        "instructions": "If the task asks for a review, what does the review have to check?",
        "criteria": [
            "Formatting or conformance to an explicit checklist",
            "Behaviour against stated requirements and tests",
            "Correctness, regressions, security or design that must be judged independently"]},
    "prior_failure": {"type": "noul",
        "instructions": "Does the task say that an earlier attempt at this same work failed?"},
}
SCORES = tuple(name for name, q in QUESTIONS.items() if q["type"] == "score")
NOULS = tuple(name for name, q in QUESTIONS.items() if q["type"] == "noul")

DEFAULTS = {"mode": "shadow", "min_confidence": 0.6, "strict_confidence": 0.8,
            "review_threshold": 0.5, "prior_failure_threshold": 0.5}
# Ranks follow the native catalogue purpose text and standard prices (checked 2026-09-27); models without
# a description or a price (daybreak previews, codex-auto-review) stay unranked and are never picked.
DEFAULT_RANKS = {
    "claude": {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4},
    "codex": {"gpt-6-luna": 1, "gpt-5.6-luna": 1, "gpt-5.6-terra": 2, "gpt-5.4": 2, "gpt-5.5": 2,
              "gpt-6-sol": 3, "gpt-5.6-sol": 3, "gpt-6-astra": 4},
}
# Effort class per reasoning level; raised one step for an underspecified task.
EFFORT_BY_REASONING = ("low", "medium", "high", "xhigh")


class PolicyError(Exception):
    """Unusable factor answers; the kind is a fixed diagnostic code."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def validate(section, ranks):
    """Normalize [policy] and per-agent capability_rank tables; ValueError on bad input."""
    if not isinstance(section, dict) or set(section) - set(DEFAULTS):
        raise ValueError("policy has unknown keys")
    cfg = dict(DEFAULTS, **section)
    if cfg["mode"] not in ("off", "shadow", "active"):
        raise ValueError('policy.mode must be "off", "shadow" or "active"')
    for key in ("min_confidence", "strict_confidence", "review_threshold", "prior_failure_threshold"):
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"policy.{key} must be a number from 0 to 1")
    if cfg["strict_confidence"] < cfg["min_confidence"]:
        raise ValueError("policy.strict_confidence must not be below policy.min_confidence")
    clean = {}
    for agent, table in ranks.items():
        if not isinstance(table, dict) or len(table) > 64:
            raise ValueError(f"{agent}.capability_rank must be a table of model = rank")
        for model, rank in table.items():
            if not isinstance(model, str) or not model or isinstance(rank, bool) or rank not in LEVELS:
                raise ValueError(f"{agent}.capability_rank values must be 1, 2, 3 or 4")
        clean[agent] = dict(table)
    cfg["ranks"] = clean
    return cfg


def questions():
    """Question map merged into the Choice request (ids carry a prefix)."""
    return {PREFIX + name: dict(question) for name, question in QUESTIONS.items()}


def _probability(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def parse(answers):
    """Validated factor answers {name: {...}}; PolicyError if any is missing or malformed."""
    if not isinstance(answers, dict):
        raise PolicyError("answers")
    parsed = {}
    for name, question in QUESTIONS.items():
        answer = answers.get(PREFIX + name)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise PolicyError("answers")
        if question["type"] == "noul":
            if not _probability(answer.get("noul")):
                raise PolicyError("range")
            parsed[name] = {"noul": float(answer["noul"])}
            continue
        levels = len(question["criteria"])
        table = answer.get("probabilities")
        keys = {str(index) for index in range(levels)}
        if not isinstance(table, dict) or set(table) != keys or not all(_probability(v) for v in table.values()):
            raise PolicyError("options")
        if abs(sum(table.values()) - 1) > 0.02:
            raise PolicyError("sum")
        confidence = answer.get("confidence")
        if not _probability(confidence):
            raise PolicyError("range")
        probabilities = [float(table[str(index)]) for index in range(levels)]
        top = max(range(levels), key=lambda index: (probabilities[index], -index))
        expected = sum(index * p for index, p in enumerate(probabilities))
        parsed[name] = {"level": top, "expected": round(expected, 4), "confidence": float(confidence),
                        "probabilities": [round(p, 4) for p in probabilities]}
    return parsed


def _level(factor, threshold):
    """Argmax when confident; otherwise the upper level adjacent to the expectation."""
    if factor["confidence"] >= threshold:
        return factor["level"], False
    raised = min(len(factor["probabilities"]) - 1, math.ceil(factor["expected"] - 1e-9))
    return max(raised, factor["level"]), raised > factor["level"]


def assess(factors, cfg):
    """Required capability level, effort class and the adjustments that produced them."""
    adjustments = []
    impact_guess = factors["impact"]["level"]
    threshold = cfg["strict_confidence"] if impact_guess >= 2 or factors["impact"]["expected"] >= 1.5 else cfg["min_confidence"]
    review = factors["review"]["noul"] >= cfg["review_threshold"]
    levels = {}
    # Review depth is speculative fan-out: it only counts when the task is a review.
    for name in ("reasoning", "impact", "scope") + (("review_depth",) if review else ()):
        levels[name], raised = _level(factors[name], threshold)
        if raised:
            adjustments.append("confidence_raise:" + name)
    reasoning, impact, scope = levels["reasoning"], levels["impact"], levels["scope"]
    level = (1, 2, 3, 3)[reasoning]
    drivers = ["reasoning"]
    impact_floor = (1, 2, 3)[impact]
    if impact_floor > level:
        level, drivers = impact_floor, ["impact"]
        adjustments.append("impact_floor")
    if reasoning == 3 and scope == 2 and level < 4:
        level, drivers = 4, ["reasoning", "scope"]
        adjustments.append("frontier_scope")
    if review:
        review_floor = (2, 3, 4)[levels["review_depth"]]
        if review_floor > level:
            level, drivers = review_floor, ["review_depth"]
            adjustments.append("review_floor")
    spec = factors["spec"]
    verification = factors["verification"]
    verified = (verification["level"] == 2 and verification["confidence"] >= threshold and
                spec["level"] == 2 and spec["confidence"] >= threshold)
    # Passing checks prove an implementation, not a diagnosis or a design choice.
    if verified and reasoning <= 1 and impact < 2 and not review and level > 1:
        level -= 1
        adjustments.append("verified_discount")
    if factors["prior_failure"]["noul"] >= cfg["prior_failure_threshold"] and level < 4:
        level += 1
        adjustments.append("prior_failure_raise")
    effort_index = reasoning
    if spec["level"] == 0 and effort_index < 3:
        effort_index += 1
    if review and levels["review_depth"] == 2:
        effort_index = max(effort_index, 2)
    return {"policy": POLICY, "level": level, "drivers": drivers, "review": review,
            "effort_class": EFFORT_BY_REASONING[effort_index], "adjustments": adjustments,
            "factor_levels": {name: factors[name]["level"] for name in SCORES},
            "confidence": {name: round(factors[name]["confidence"], 4) for name in SCORES}}


def output_rate(option):
    price = option.get("price_reference") or {}
    rate = price.get("output") if price.get("status") in ("fresh", "stale") else None
    return rate if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate >= 0 else None


def _effort_for(option_efforts, wanted):
    """Nearest supported effort at or above the wanted class, else the highest below."""
    if option_efforts == [None]:
        return None
    ranked = sorted(option_efforts, key=lambda e: EFFORT_ORDER.index(e) if e in EFFORT_ORDER else len(EFFORT_ORDER))
    target = EFFORT_ORDER.index(wanted)
    for effort in ranked:
        if effort in EFFORT_ORDER and EFFORT_ORDER.index(effort) >= target:
            return effort
    return ranked[-1]


def select(assessment, options, ranks):
    """(option id or None, details) — cheapest ranked model meeting the level, then effort."""
    by_model = {}
    for option_id, option in options.items():
        by_model.setdefault(option["model"], {})[option["effort"]] = option_id
    ranked = {model: ranks[model] for model in by_model if model in ranks}
    if not ranked:
        return None, {"status": "unranked"}
    level = assessment["level"]
    eligible = [model for model, rank in ranked.items() if rank >= level]
    status = "met"
    if not eligible:
        top = max(ranked.values())
        eligible = [model for model, rank in ranked.items() if rank == top]
        status = "capped"

    def cost(model):
        rates = [output_rate(options[oid]) for oid in by_model[model].values()]
        known = [rate for rate in rates if rate is not None]
        # Cheapest adequate model wins even when it is more capable; rank only breaks price ties.
        # Unknown prices are not free: they sort after every known price.
        return (min(known) if known else math.inf, ranked[model], model)

    model = min(eligible, key=cost)
    effort = _effort_for(list(by_model[model]), assessment["effort_class"])
    return by_model[model][effort], {"status": status, "rank": ranked[model]}


def price_ratio(option, options):
    """Output-rate multiple over the cheapest priced offered model; None when unknown."""
    rate = output_rate(option)
    known = [r for r in (output_rate(o) for o in options.values()) if r is not None and r > 0]
    if rate is None or not known:
        return None
    return round(rate / min(known), 4)


def compare(policy_option, choice_option, ranks):
    """How the factor recommendation relates to the direct Choice."""
    if policy_option is None or choice_option is None:
        return "unknown"
    if policy_option["model"] == choice_option["model"]:
        return "identical" if policy_option["effort"] == choice_option["effort"] else "same_model"
    p, c = ranks.get(policy_option["model"]), ranks.get(choice_option["model"])
    if p is None or c is None or p == c:
        return "other_model"
    return "policy_higher" if p > c else "policy_lower"
