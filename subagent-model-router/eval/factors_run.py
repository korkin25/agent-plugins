#!/usr/bin/env python3
"""Factor-policy benchmark: offline metrics from saved answers; live queries only with --live.

Offline (no network):
  factors_run.py --answers RESULTS.jsonl [--report REPORT.json] [--worst N]
  factors_run.py --check-labels
Live (explicit, sends every case once per repeat with the factor questions only):
  factors_run.py --live --output NEW.jsonl [--repeats 2] [--timeout 20]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("factors_cases.json")
sys.path.insert(0, str(ROOT / "lib"))
import router_factors as rf  # noqa: E402

EFFORTS = ("low", "medium", "high", "xhigh")
FACTORS_SCORE = ("reasoning", "spec", "verification", "scope", "impact", "review_depth")
FACTORS_NOUL = ("review", "prior_failure")
SEED = 20260927


# --- dataset ------------------------------------------------------------------

def load_cases(path=CASES):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    cases = data["cases"] if isinstance(data, dict) else data
    return cases, hashlib.sha256(raw).hexdigest()


def validate_cases(cases):
    """List of problems (empty when every case is complete and consistent)."""
    problems, seen = [], set()
    for c in cases:
        cid = c.get("id")
        for field in ("id", "group", "language", "description", "task", "expected", "rationale"):
            if not isinstance(c.get(field), (str, dict)) or not c.get(field):
                problems.append(f"{cid}: missing {field}")
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        e = c.get("expected") or {}
        lo, hi = e.get("min_level"), e.get("max_level")
        if lo not in rf.LEVELS or hi not in rf.LEVELS or lo > hi:
            problems.append(f"{cid}: bad level band")
        if e.get("effort_min") not in EFFORTS or e.get("effort_max") not in EFFORTS or \
                EFFORTS.index(e.get("effort_min", "low")) > EFFORTS.index(e.get("effort_max", "low")):
            problems.append(f"{cid}: bad effort band")
        f = e.get("factors") or {}
        for name in ("reasoning", "spec", "verification", "scope", "impact"):
            size = len(rf.QUESTIONS[name]["criteria"])
            if f.get(name) not in range(size) or isinstance(f.get(name), bool):
                problems.append(f"{cid}: bad factor {name}")
        for name in FACTORS_NOUL:
            if not isinstance(f.get(name), bool):
                problems.append(f"{cid}: bad factor {name}")
        depth = f.get("review_depth")
        if f.get("review") and depth not in (0, 1, 2):
            problems.append(f"{cid}: review case needs review_depth")
        if not f.get("review") and depth is not None:
            problems.append(f"{cid}: review_depth set on a non-review case")
    return problems


def label_answers(factors):
    """One-hot, fully confident answers equal to the labels (the rubric oracle)."""
    answers = {}
    for name, q in rf.QUESTIONS.items():
        if q["type"] == "noul":
            answers[rf.PREFIX + name] = {"type": "noul", "noul": 1.0 if factors[name] else 0.0}
        else:
            value = factors.get(name)
            value = 0 if value is None else value
            answers[rf.PREFIX + name] = {"type": "score", "confidence": 1.0,
                                         "probabilities": {str(i): float(i == value)
                                                           for i in range(len(q["criteria"]))}}
    return answers


def rubric_assessment(factors, cfg=None):
    cfg = cfg or rf.validate({}, {})
    return rf.assess(rf.parse(label_answers(factors)), cfg)


# --- metrics --------------------------------------------------------------------

def _rows(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if "case" in obj:
            rows.append(obj)
    return rows


def evaluate_row(row, cfg):
    """(parsed factors, assessment) or (None, error kind)."""
    if row.get("error"):
        return None, row["error"]
    try:
        parsed = rf.parse(row.get("answers"))
    except rf.PolicyError as exc:
        return None, "policy:" + exc.kind
    return parsed, rf.assess(parsed, cfg)


def _mean(values):
    return round(statistics.mean(values), 4) if values else None


def _rate(num, den):
    return round(num / den, 4) if den else None


def metrics(rows, cases, cfg=None, worst=10):
    cfg = cfg or rf.validate({}, {})
    by_id = {c["id"]: c for c in cases}
    unknown = sorted({r["case"] for r in rows if r["case"] not in by_id})
    rows = [r for r in rows if r["case"] in by_id]
    evaluated, failures = [], {}
    for r in rows:
        parsed, result = evaluate_row(r, cfg)
        if parsed is None:
            failures[result] = failures.get(result, 0) + 1
            continue
        evaluated.append((r, parsed, result))

    factor = {}
    for name in FACTORS_SCORE:
        hits, conf, n = 0, [], 0
        for r, parsed, _ in evaluated:
            label = by_id[r["case"]]["expected"]["factors"].get(name)
            if label is None:
                continue
            n += 1
            hits += parsed[name]["level"] == label
            conf.append(parsed[name]["confidence"])
        factor[name] = {"n": n, "accuracy": _rate(hits, n), "mean_confidence": _mean(conf)}
    for name in FACTORS_NOUL:
        threshold = cfg["review_threshold"] if name == "review" else cfg["prior_failure_threshold"]
        hits = fp = fn = 0
        pos, neg = [], []
        for r, parsed, _ in evaluated:
            label = by_id[r["case"]]["expected"]["factors"][name]
            p = parsed[name]["noul"]
            said = p >= threshold
            hits += said == label
            fp += said and not label
            fn += label and not said
            (pos if label else neg).append(p)
        factor[name] = {"n": len(evaluated), "accuracy": _rate(hits, len(evaluated)),
                        "false_positive": fp, "false_negative": fn,
                        "mean_p_when_true": _mean(pos), "mean_p_when_false": _mean(neg)}

    within = under = over = eff_within = 0
    overshoot, shortfall, excess_min = [], [], []
    groups, confusion, per_case = {}, {}, {}
    for r, parsed, a in evaluated:
        c = by_id[r["case"]]
        e = c["expected"]
        level = a["level"]
        g = groups.setdefault(c["group"], {"n": 0, "under": 0, "within": 0, "over": 0,
                                           "effort_within": 0})
        g["n"] += 1
        key = f"{e['min_level']}->{level}"
        confusion[key] = confusion.get(key, 0) + 1
        if level < e["min_level"]:
            under += 1
            g["under"] += 1
            shortfall.append(e["min_level"] - level)
        elif level > e["max_level"]:
            over += 1
            g["over"] += 1
            overshoot.append(level - e["max_level"])
        else:
            within += 1
            g["within"] += 1
        if level > e["min_level"]:
            excess_min.append(level - e["min_level"])
        effort_idx = EFFORTS.index(a["effort_class"])
        if EFFORTS.index(e["effort_min"]) <= effort_idx <= EFFORTS.index(e["effort_max"]):
            eff_within += 1
            g["effort_within"] += 1
        mismatches = [name for name in FACTORS_SCORE
                      if e["factors"].get(name) is not None and parsed[name]["level"] != e["factors"][name]]
        mismatches += [name for name in FACTORS_NOUL
                       if (parsed[name]["noul"] >= (cfg["review_threshold"] if name == "review"
                                                   else cfg["prior_failure_threshold"])) != e["factors"][name]]
        per_case.setdefault(c["id"], []).append({"repeat": r.get("repeat"), "level": level,
                                                 "effort": a["effort_class"], "adjustments": a["adjustments"],
                                                 "mismatches": mismatches,
                                                 "argmax": {n: parsed[n]["level"] for n in rf.SCORES}})

    disagree_level = disagree_effort = disagree_factor = multi = 0
    for runs in per_case.values():
        if len(runs) < 2:
            continue
        multi += 1
        disagree_level += len({x["level"] for x in runs}) > 1
        disagree_effort += len({x["effort"] for x in runs}) > 1
        disagree_factor += len({json.dumps(x["argmax"], sort_keys=True) for x in runs}) > 1

    def badness(item):
        cid, runs = item
        e = by_id[cid]["expected"]
        short = max(e["min_level"] - x["level"] for x in runs)
        excess = max(x["level"] - e["max_level"] for x in runs)
        miss = max(len(x["mismatches"]) for x in runs)
        return (-max(short, 0), -max(excess, 0), -miss, cid)

    worst_cases = []
    for cid, runs in sorted(per_case.items(), key=badness)[:worst]:
        e = by_id[cid]["expected"]
        worst_cases.append({"case": cid, "group": by_id[cid]["group"],
                            "band": [e["min_level"], e["max_level"]],
                            "levels": [x["level"] for x in runs], "efforts": [x["effort"] for x in runs],
                            "mismatched_factors": sorted({m for x in runs for m in x["mismatches"]}),
                            "adjustments": sorted({a for x in runs for a in x["adjustments"]})})

    n = len(evaluated)
    return {
        "attempts": len(rows), "evaluated": n, "failures": failures, "unknown_cases": unknown,
        "cases_covered": len(per_case), "cases_total": len(cases),
        "factors": factor,
        "level": {"within_band_rate": _rate(within, n),
                  "under_routing_rate": _rate(under, n),  # primary metric
                  "mean_under_shortfall": _mean(shortfall),
                  "over_routing_rate": _rate(over, n),
                  "mean_overshoot_above_max": _mean(overshoot),
                  "mean_excess_above_min": _mean(excess_min),
                  "confusion_min_level_to_observed": dict(sorted(confusion.items()))},
        "effort": {"within_band_rate": _rate(eff_within, n)},
        "repeats": {"cases_with_repeats": multi, "level_disagreement": disagree_level,
                    "effort_disagreement": disagree_effort, "factor_argmax_disagreement": disagree_factor},
        "groups": dict(sorted(groups.items())),
        "worst_cases": worst_cases,
    }


# --- live -------------------------------------------------------------------------

def _load_router():
    loader = importlib.machinery.SourceFileLoader("router_factors_eval", str(ROOT / "bin/subagent-model-router"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sanitize_answers(answers, questions):
    """Keep only declared factor ids and only numeric probability/confidence/noul fields."""
    clean = {}
    for qid, answer in (answers or {}).items():
        if qid not in questions or not isinstance(answer, dict):
            continue
        item = {"type": answer.get("type") if answer.get("type") in ("score", "noul") else None}
        table = answer.get("probabilities")
        if isinstance(table, dict):
            item["probabilities"] = {str(k): v for k, v in table.items() if _number(v)}
        for field in ("confidence", "noul"):
            if _number(answer.get(field)):
                item[field] = answer[field]
        clean[qid] = item
    return clean


def make_factor_parser(router):
    """Response parser for a factor-only request (the Choice parser requires a selection)."""
    def parse(raw, questions, header_request_id=None):
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise router.JevError("json") from None
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise router.JevError("answers")
        usage = data.get("usage")
        return {"answers": _sanitize_answers(data["answers"], questions),
                "usage": {k: v for k, v in usage.items() if k in ("input_tokens", "output_tokens", "cost")
                          and _number(v) and v >= 0} if isinstance(usage, dict) else {},
                "jev_model": data.get("model") if isinstance(data.get("model"), str) else None}
    return parse


def run_live(args, cases, dataset_sha):
    target = Path(args.output)
    if target.exists():
        raise SystemExit("Refusing to overwrite evaluation output")
    router = _load_router()
    try:
        cfg = router.load_config()
    except router.ConfigError as exc:
        raise SystemExit("Router config unusable: " + str(exc)) from None
    if cfg is None:
        raise SystemExit("Router config unavailable")
    key, problem = router.read_key(cfg["key_file"])
    if key is None:
        raise SystemExit("Configured key unavailable: " + str(problem))
    cfg = dict(cfg, timeout_seconds=args.timeout)
    # Reuse the plugin's own HTTP path (_exchange inside ask_jev) with a factor-only parser.
    router.parse_response = make_factor_parser(router)
    questions = rf.questions()
    jobs = [(c, repeat) for repeat in range(args.repeats) for c in cases]
    random.Random(SEED).shuffle(jobs)
    meta = {"dataset_sha256": dataset_sha, "repeats": args.repeats, "model": cfg["model"],
            "provider": cfg["provider"], "policy": rf.POLICY, "policy_defaults": rf.DEFAULTS,
            "questions_sha256": hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest(),
            "timeout_seconds": args.timeout, "seed": SEED,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": "Factor questions only (no selection question); synthetic labels; one request per case "
                    "per repeat."}
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with target.open("x", encoding="utf-8") as out:
        out.write(json.dumps({"meta": meta}, ensure_ascii=False) + "\n")
        out.flush()
        for idx, (case, repeat) in enumerate(jobs):
            state = router.build_state(case["description"], case["task"])
            row = {"case": case["id"], "repeat": repeat}
            try:
                if state["input_quality"]["oversized"]:
                    raise router.JevError("input_size")
                response = router.ask_jev(cfg, key, state, questions)
                row.update(answers=response["answers"], latency_ms=response["latency_ms"],
                           usage=response.get("usage", {}))
                if response.get("jev_model"):
                    row["jev_model"] = response["jev_model"]
            except router.JevError as exc:
                row.update(error=exc.kind, latency_ms=exc.latency_ms)
            rows.append(row)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{idx + 1}/{len(jobs)} {case['id']} {'error:' + row['error'] if 'error' in row else 'ok'}",
                  flush=True)
        summary = metrics(rows, cases, worst=args.worst)
        ok = [r for r in rows if "error" not in r]
        summary["mean_latency_ms"] = _mean([r["latency_ms"] for r in ok if _number(r.get("latency_ms"))])
        costs = [r["usage"]["cost"] for r in ok if "cost" in r.get("usage", {})]
        summary["reported_cost_sum"] = sum(costs) if costs else None
        out.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")
    return summary


# --- cli ----------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--answers", help="offline: saved results JSONL (from --live or synthetic)")
    mode.add_argument("--live", action="store_true", help="send real requests (needs --output)")
    mode.add_argument("--check-labels", action="store_true",
                      help="validate the cases and compare each band with the rubric level of its labels")
    p.add_argument("--cases", default=str(CASES))
    p.add_argument("--output", help="live: new results JSONL (never overwritten)")
    p.add_argument("--report", help="offline: write the metrics JSON here (never overwritten)")
    p.add_argument("--repeats", type=int, default=2, choices=(1, 2, 3))
    p.add_argument("--timeout", type=float, default=20.0, help="live: per-request budget in seconds")
    p.add_argument("--worst", type=int, default=10)
    args = p.parse_args(argv)
    cases, sha = load_cases(args.cases)
    problems = validate_cases(cases)
    if args.check_labels:
        for c in cases:
            a = rubric_assessment(c["expected"]["factors"])
            e = c["expected"]
            flag = "ok" if a["level"] == e["min_level"] and a["effort_class"] == e["effort_min"] else "DIFF"
            print(f"{flag:4} {c['id']:40} rubric={a['level']}/{a['effort_class']} "
                  f"band={e['min_level']}-{e['max_level']} effort={e['effort_min']}-{e['effort_max']}")
            if flag != "ok":
                problems.append(f"{c['id']}: band does not start at the rubric level")
        print(f"cases={len(cases)} sha256={sha} problems={len(problems)}")
        for line in problems:
            print("  " + line)
        return 1 if problems else 0
    if problems:
        raise SystemExit("Invalid cases: " + "; ".join(problems))
    if args.live:
        if not args.output:
            p.error("--live requires --output")
        summary = run_live(args, cases, sha)
    else:
        if args.report and Path(args.report).exists():
            raise SystemExit("Refusing to overwrite report")
        summary = metrics(_rows(args.answers), cases, worst=args.worst)
        summary["dataset_sha256"] = sha
        if args.report:
            with open(args.report, "x", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
