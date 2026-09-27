"""Synthetic-only tests of the factor benchmark metrics (no network, no config, no keys)."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import factors_run as fr  # noqa: E402


def factors(r=0, spec=2, ver=0, scope=0, impact=0, review=False, depth=None, pf=False):
    return {"reasoning": r, "spec": spec, "verification": ver, "scope": scope, "impact": impact,
            "review": review, "review_depth": depth, "prior_failure": pf}


def case(cid, f, band, effort=("low", "medium"), group="g"):
    return {"id": cid, "group": group, "language": "en", "description": "d", "task": "t", "rationale": "r",
            "expected": {"min_level": band[0], "max_level": band[1], "effort_min": effort[0],
                         "effort_max": effort[1], "factors": f}}


def row(cid, f, repeat=0):
    return {"case": cid, "repeat": repeat, "answers": fr.label_answers(f), "latency_ms": 5,
            "usage": {"input_tokens": 1}}


CASES = [
    case("light", factors(), (1, 2)),                                   # rubric level 1
    case("risky", factors(impact=2), (3, 4), group="h"),                # rubric level 3
    case("review", factors(r=2, spec=1, scope=1, impact=1, review=True, depth=2), (4, 4),
         ("high", "xhigh"), group="h"),                                 # rubric level 4
]


class MetricsTests(unittest.TestCase):
    def test_perfect_answers(self):
        rows = [row(c["id"], c["expected"]["factors"], rep) for c in CASES for rep in (0, 1)]
        m = fr.metrics(rows, CASES)
        self.assertEqual(m["evaluated"], 6)
        self.assertEqual(m["level"]["within_band_rate"], 1.0)
        self.assertEqual(m["level"]["under_routing_rate"], 0.0)
        self.assertEqual(m["level"]["over_routing_rate"], 0.0)
        self.assertEqual(m["effort"]["within_band_rate"], 1.0)
        self.assertEqual(m["repeats"], {"cases_with_repeats": 3, "level_disagreement": 0,
                                        "effort_disagreement": 0, "factor_argmax_disagreement": 0})
        for name in ("reasoning", "spec", "verification", "scope", "impact", "review", "prior_failure"):
            self.assertEqual(m["factors"][name]["accuracy"], 1.0, name)
        # review_depth is scored only where the label defines it.
        self.assertEqual(m["factors"]["review_depth"]["n"], 2)
        self.assertEqual(m["factors"]["reasoning"]["mean_confidence"], 1.0)

    def test_under_routing_is_counted_and_worst(self):
        wrong = factors()  # risky case answered as harmless -> level 1 < min 3
        rows = [row("light", CASES[0]["expected"]["factors"]), row("risky", wrong),
                row("review", CASES[2]["expected"]["factors"])]
        m = fr.metrics(rows, CASES)
        self.assertAlmostEqual(m["level"]["under_routing_rate"], round(1 / 3, 4))
        self.assertEqual(m["level"]["mean_under_shortfall"], 2)
        self.assertEqual(m["factors"]["impact"]["accuracy"], round(2 / 3, 4))
        self.assertEqual(m["worst_cases"][0]["case"], "risky")
        self.assertIn("impact", m["worst_cases"][0]["mismatched_factors"])
        self.assertEqual(m["groups"]["h"]["under"], 1)
        self.assertEqual(m["level"]["confusion_min_level_to_observed"]["3->1"], 1)

    def test_over_routing_and_overshoot(self):
        rows = [row("light", factors(r=3, scope=2))]  # level 4 on a 1-2 band
        m = fr.metrics(rows, CASES)
        self.assertEqual(m["level"]["over_routing_rate"], 1.0)
        self.assertEqual(m["level"]["mean_overshoot_above_max"], 2)
        self.assertEqual(m["level"]["mean_excess_above_min"], 3)
        self.assertEqual(m["effort"]["within_band_rate"], 0.0)  # xhigh outside low-medium

    def test_repeat_disagreement(self):
        f = CASES[0]["expected"]["factors"]
        rows = [row("light", f, 0), row("light", factors(r=2), 1)]
        m = fr.metrics(rows, CASES)
        self.assertEqual(m["repeats"]["level_disagreement"], 1)
        self.assertEqual(m["repeats"]["effort_disagreement"], 1)
        self.assertEqual(m["repeats"]["factor_argmax_disagreement"], 1)

    def test_noul_false_positive_and_negative(self):
        rows = [row("light", factors(review=True, depth=0)),  # review said on a non-review
                row("review", factors(r=2, spec=1, scope=1, impact=1))]  # review missed
        m = fr.metrics(rows, CASES)
        self.assertEqual(m["factors"]["review"]["false_positive"], 1)
        self.assertEqual(m["factors"]["review"]["false_negative"], 1)
        self.assertEqual(m["factors"]["review"]["accuracy"], 0.0)

    def test_errors_and_malformed_answers_are_failures(self):
        bad = row("light", CASES[0]["expected"]["factors"])
        del bad["answers"]["f_scope"]
        rows = [{"case": "light", "repeat": 0, "error": "timeout", "latency_ms": 20000}, bad,
                {"case": "nope", "repeat": 0, "error": "network"}]
        m = fr.metrics(rows, CASES)
        self.assertEqual(m["evaluated"], 0)
        self.assertEqual(m["failures"], {"timeout": 1, "policy:answers": 1})
        self.assertEqual(m["unknown_cases"], ["nope"])
        self.assertIsNone(m["level"]["under_routing_rate"])

    def test_low_confidence_raise_uses_policy(self):
        # Probability mass split 0/1 on impact with low confidence: the policy raises to the upper level.
        r = row("light", CASES[0]["expected"]["factors"])
        r["answers"]["f_impact"] = {"type": "score", "confidence": 0.3,
                                    "probabilities": {"0": 0.55, "1": 0.45, "2": 0.0}}
        m = fr.metrics([r], CASES)
        self.assertEqual(m["factors"]["impact"]["accuracy"], 1.0)  # argmax still 0
        self.assertEqual(m["worst_cases"][0]["levels"], [2])
        self.assertEqual(m["level"]["within_band_rate"], 1.0)


class DatasetTests(unittest.TestCase):
    def test_frozen_cases_are_valid_and_start_at_rubric_level(self):
        cases, sha = fr.load_cases()
        self.assertGreaterEqual(len(cases), 36)
        self.assertEqual(fr.validate_cases(cases), [])
        self.assertEqual(len(sha), 64)
        for c in cases:
            e = c["expected"]
            a = fr.rubric_assessment(e["factors"])
            self.assertEqual(a["level"], e["min_level"], c["id"])
            self.assertEqual(a["effort_class"], e["effort_min"], c["id"])
        langs = {c["language"] for c in cases}
        self.assertEqual(langs, {"en", "ru"})

    def test_validator_rejects_inverted_band(self):
        bad = case("x", factors(), (3, 2))
        self.assertTrue(fr.validate_cases([bad]))

    def test_offline_cli_refuses_to_overwrite_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            answers = Path(tmp) / "answers.jsonl"
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(json.dumps({"cases": CASES}), encoding="utf-8")
            answers.write_text(json.dumps({"meta": {}}) + "\n" +
                               "\n".join(json.dumps(row(c["id"], c["expected"]["factors"])) for c in CASES) +
                               "\n", encoding="utf-8")
            report = Path(tmp) / "report.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(fr.main(["--answers", str(answers), "--cases", str(cases_path),
                                          "--report", str(report)]), 0)
            self.assertEqual(json.loads(report.read_text())["level"]["within_band_rate"], 1.0)
            with self.assertRaises(SystemExit):
                fr.main(["--answers", str(answers), "--cases", str(cases_path), "--report", str(report)])


class LiveHelpersTests(unittest.TestCase):
    def test_sanitize_drops_undeclared_and_non_numeric(self):
        questions = {"f_spec": {}}
        clean = fr._sanitize_answers({"f_spec": {"type": "score", "probabilities": {"0": 0.5, "1": "x"},
                                                 "confidence": 0.9, "extra": "secret"},
                                      "selection": {"type": "choice"}}, questions)
        self.assertEqual(clean, {"f_spec": {"type": "score", "probabilities": {"0": 0.5}, "confidence": 0.9}})

    def test_factor_parser_through_router_module(self):
        router = fr._load_router()
        parse = fr.make_factor_parser(router)
        questions = fr.rf.questions()
        body = {"model": "jev-test", "usage": {"input_tokens": 10, "cost": 0.001, "note": "x"},
                "answers": fr.label_answers(fr.load_cases()[0][0]["expected"]["factors"])}
        out = parse(json.dumps(body).encode(), questions, "req-1")
        self.assertEqual(set(out["answers"]), set(questions))
        self.assertEqual(out["usage"], {"input_tokens": 10, "cost": 0.001})
        fr.rf.parse(out["answers"])  # policy accepts the sanitized answers
        with self.assertRaises(router.JevError):
            parse(b"not json", questions)


if __name__ == "__main__":
    unittest.main()
