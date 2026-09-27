"""Factor policy: atomic Jev ratings turned into a launch pair by code, next to the direct Choice."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "lib"))

import router_factors as rf  # noqa: E402
from test_router import Sandbox, Reply, described_catalog, router, v2_args  # noqa: E402


def score(level, levels=3, confidence=1.0, probabilities=None):
    table = probabilities or [float(index == level) for index in range(levels)]
    return {"type": "score", "score": float(level), "probabilities": {str(i): p for i, p in enumerate(table)},
            "confidence": confidence}


def noul(value):
    return {"type": "noul", "noul": value}


def answers(reasoning=1, spec=1, verification=1, scope=0, impact=0, review=0.0, review_depth=0,
            prior_failure=0.0, **overrides):
    s = lambda value, levels=3: value if isinstance(value, dict) else score(value, levels)
    n = lambda value: value if isinstance(value, dict) else noul(value)
    raw = {"reasoning": s(reasoning, 4), "spec": s(spec), "verification": s(verification),
           "scope": s(scope), "impact": s(impact), "review": n(review),
           "review_depth": s(review_depth), "prior_failure": n(prior_failure)}
    raw.update(overrides)
    return {rf.PREFIX + name: value for name, value in raw.items()}


CFG = rf.validate({}, dict(rf.DEFAULT_RANKS))


def assess(**kwargs):
    return rf.assess(rf.parse(answers(**kwargs)), CFG)


def option(model, effort, output=None):
    price = {"status": "fresh", "output": output} if output is not None else {"status": "unknown"}
    return {"model": model, "effort": effort, "price_reference": price}


CLAUDE_OPTIONS = {
    "h": option("haiku", None, 5), "s-low": option("sonnet", "low", 10), "s-high": option("sonnet", "high", 10),
    "o-low": option("opus", "low", 20), "o-high": option("opus", "high", 20), "o-xhigh": option("opus", "xhigh", 20),
    "f-high": option("fable", "high", 50), "f-xhigh": option("fable", "xhigh", 50),
}


class ParseTests(unittest.TestCase):
    def test_valid_answers_keep_level_expectation_and_confidence(self):
        parsed = rf.parse(answers(reasoning=2, verification=2))
        self.assertEqual(parsed["reasoning"]["level"], 2)
        self.assertEqual(parsed["verification"]["expected"], 2.0)
        self.assertEqual(parsed["review"], {"noul": 0.0})

    def test_missing_wrong_type_bad_levels_and_sum_are_rejected(self):
        broken = answers()
        del broken["f_scope"]
        cases = {"answers": broken, "answers2": answers(scope=noul(.5)),
                 "options": answers(spec={"type": "score", "probabilities": {"0": 1.0}, "confidence": 1}),
                 "sum": answers(spec=score(0, probabilities=[.5, .1, .1])),
                 "range": answers(review=noul(1.5))}
        for name, value in cases.items():
            with self.subTest(name), self.assertRaises(rf.PolicyError):
                rf.parse(value)
        with self.assertRaises(rf.PolicyError):
            rf.parse(None)


class AssessTests(unittest.TestCase):
    def test_mechanical_verified_task_is_light(self):
        result = assess(reasoning=0, spec=2, verification=2)
        self.assertEqual((result["level"], result["effort_class"]), (1, "low"))

    def test_specified_verified_implementation_gets_one_step_discount(self):
        result = assess(reasoning=1, spec=2, verification=2, impact=1)
        self.assertEqual(result["level"], 1)
        self.assertIn("verified_discount", result["adjustments"])

    def test_discount_needs_confident_checks_and_harmless_impact(self):
        self.assertEqual(assess(reasoning=1, spec=2, verification=2, impact=2)["level"], 3)
        low = score(2, confidence=.4, probabilities=[.3, .1, .6])
        self.assertEqual(assess(reasoning=1, spec=2, verification=low)["level"], 2)

    def test_checks_do_not_discount_a_diagnosis(self):
        result = assess(reasoning=2, spec=2, verification=2, impact=1)
        self.assertEqual(result["level"], 3)
        self.assertNotIn("verified_discount", result["adjustments"])
        self.assertEqual(assess(reasoning=2, spec=2, verification=2, impact=1, prior_failure=.99)["level"], 4)

    def test_diagnosis_is_strong_and_security_across_components_is_frontier(self):
        self.assertEqual(assess(reasoning=2, spec=0)["level"], 3)
        self.assertEqual(assess(reasoning=2, spec=0)["effort_class"], "xhigh")
        result = assess(reasoning=3, scope=2)
        self.assertEqual(result["level"], 4)
        self.assertIn("frontier_scope", result["adjustments"])

    def test_impact_floor_lifts_a_simple_but_dangerous_task(self):
        result = assess(reasoning=0, impact=2)
        self.assertEqual((result["level"], result["drivers"]), (3, ["impact"]))

    def test_review_depth_counts_only_for_a_review(self):
        self.assertEqual(assess(reasoning=1, review=.1, review_depth=2)["level"], 2)
        result = assess(reasoning=1, review=.9, review_depth=2)
        self.assertEqual((result["level"], result["review"]), (4, True))
        self.assertEqual(assess(reasoning=1, review=.9, review_depth=0)["level"], 2)
        uncertain = score(1, confidence=.3, probabilities=[.1, .5, .4])
        self.assertNotIn("confidence_raise:review_depth",
                         assess(review=.1, review_depth=uncertain)["adjustments"])

    def test_low_confidence_takes_the_upper_adjacent_level(self):
        uncertain = score(1, 4, confidence=.4, probabilities=[0, .55, .45, 0])
        result = assess(reasoning=uncertain)
        self.assertEqual(result["level"], 3)
        self.assertIn("confidence_raise:reasoning", result["adjustments"])

    def test_high_impact_uses_the_stricter_confidence_threshold(self):
        moderate = score(1, 4, confidence=.7, probabilities=[0, .75, .25, 0])
        self.assertNotIn("confidence_raise:reasoning", assess(reasoning=moderate)["adjustments"])
        self.assertIn("confidence_raise:reasoning", assess(reasoning=moderate, impact=2)["adjustments"])

    def test_prior_failure_raises_one_step_up_to_frontier(self):
        self.assertEqual(assess(reasoning=1, prior_failure=.9)["level"], 3)
        self.assertEqual(assess(reasoning=3, scope=2, prior_failure=.9)["level"], 4)


class SelectTests(unittest.TestCase):
    def test_cheapest_model_meeting_level_with_nearest_effort(self):
        pick = lambda level, effort: rf.select({"level": level, "effort_class": effort}, CLAUDE_OPTIONS, rf.DEFAULT_RANKS["claude"])
        self.assertEqual(pick(1, "low"), ("h", {"status": "met", "rank": 1}))
        self.assertEqual(pick(2, "medium")[0], "s-high")
        self.assertEqual(pick(3, "xhigh")[0], "o-xhigh")
        self.assertEqual(pick(4, "max")[0], "f-xhigh")  # highest supported below the wanted class

    def test_capped_and_unranked(self):
        options = {k: v for k, v in CLAUDE_OPTIONS.items() if not k.startswith("f")}
        self.assertEqual(rf.select({"level": 4, "effort_class": "high"}, options, rf.DEFAULT_RANKS["claude"]),
                         ("o-high", {"status": "capped", "rank": 3}))
        self.assertEqual(rf.select({"level": 2, "effort_class": "high"}, options, {}), (None, {"status": "unranked"}))

    def test_unknown_price_is_not_free(self):
        options = {"a": option("cheap-known", "low", 1), "b": option("unknown-price", "low")}
        self.assertEqual(rf.select({"level": 2, "effort_class": "low"}, options,
                                   {"cheap-known": 2, "unknown-price": 2})[0], "a")

    def test_price_ratio_and_comparison(self):
        self.assertEqual(rf.price_ratio(CLAUDE_OPTIONS["o-high"], CLAUDE_OPTIONS), 4.0)
        self.assertIsNone(rf.price_ratio(option("x", "low"), CLAUDE_OPTIONS))
        ranks = rf.DEFAULT_RANKS["claude"]
        compare = lambda a, b: rf.compare(CLAUDE_OPTIONS[a], CLAUDE_OPTIONS[b], ranks)
        self.assertEqual(compare("o-high", "o-high"), "identical")
        self.assertEqual(compare("o-high", "o-low"), "same_model")
        self.assertEqual(compare("f-high", "o-high"), "policy_higher")
        self.assertEqual(compare("s-high", "o-high"), "policy_lower")
        self.assertEqual(rf.compare(None, CLAUDE_OPTIONS["h"], ranks), "unknown")


class ConfigTests(unittest.TestCase):
    def test_defaults_and_capability_rank(self):
        cfg = router.normalize_config({"codex": {"capability_rank": {"gpt-5.5": 2}}})
        self.assertEqual(cfg["policy"]["mode"], "shadow")
        self.assertEqual(cfg["policy"]["ranks"], {"claude": rf.DEFAULT_RANKS["claude"], "codex": {"gpt-5.5": 2}})
        self.assertNotIn("capability_rank", cfg["codex"])

    def test_invalid_policy_disables_only_the_policy(self):
        for bad in ({"policy": {"mode": "loud"}}, {"policy": {"unknown": 1}},
                    {"policy": {"min_confidence": .9, "strict_confidence": .5}},
                    {"claude": {"capability_rank": {"opus": 7}}}):
            with self.subTest(bad):
                cfg = router.normalize_config(bad)
                self.assertEqual(cfg["policy"]["mode"], "off")
                self.assertIn("_policy_error", cfg)
                self.assertTrue(cfg["enabled"])


class RouterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = router.normalize_config({"codex": {"capability_rank": {"future-fast": 1, "future-strong": 3}}})
        with mock.patch.object(router, "codex_catalog", return_value=(
                described_catalog({"future-fast": ["low"], "future-strong": ["high", "ultra"]}), None)):
            self.options = router.selection_options(self.cfg, "codex")
        self.questions = router.selection_questions(self.options, "codex")
        self.questions.update(rf.questions())
        self.fast = next(k for k, v in self.options.items() if v["model"] == "future-fast")

    def body(self, factor_answers):
        return json.dumps({"model": "jev-1.13.0", "answers": dict(
            {"selection": {"type": "choice", "choice": self.fast, "confidence": .9,
                           "probabilities": {k: float(k == self.fast) for k in self.options}}}, **factor_answers)}).encode()

    def test_factor_answers_ride_along_and_policy_disagrees_upward(self):
        result = router.parse_response(self.body(answers(reasoning=2)), self.questions)
        self.assertEqual(result["answers"]["selection"]["confidence"], .9)
        info, chosen = router.evaluate_policy(self.cfg, "codex", self.options, result, self.options[self.fast])
        self.assertEqual((info["outcome"], info["level"], info["model"], info["agreement"]),
                         ("success", 3, "future-strong", "policy_higher"))
        self.assertEqual(chosen["model"], "future-strong")

    def test_missing_factor_answers_keep_the_choice(self):
        result = router.parse_response(self.body({}), self.questions)
        self.assertEqual(result["choice"], self.fast)
        info, chosen = router.evaluate_policy(self.cfg, "codex", self.options, result, self.options[self.fast])
        self.assertEqual((info["outcome"], chosen), ("error:answers", None))

    def test_unexpected_answer_key_is_rejected(self):
        with self.assertRaises(router.JevError):
            router.parse_response(self.body({"surprise": noul(.5)}), self.questions)


class HookTests(Sandbox):
    FACTORS = answers(reasoning=2, spec=0)

    def write_ranked_config(self, **values):
        self.write_config(**values)
        with open(self.config, "a") as fh:
            fh.write('[codex.capability_rank]\n"gpt-5.6-luna" = 1\n"gpt-5.5" = 2\n"gpt-5.6-terra" = 3\n')

    def test_shadow_policy_is_recorded_and_announced_without_changing_launch(self):
        self.serve(Reply(body={"_fixture_choice_index": 0, "_factors": self.FACTORS}))
        self.write_ranked_config()
        rc, out, err, _ = self.codex_hook(v2_args())
        self.assertEqual((rc, err), (0, ""))
        output = json.loads(out)
        row = self.last_row()
        self.assertEqual(row["reason"], "choice")
        self.assertEqual(output["hookSpecificOutput"]["updatedInput"]["model"], row["choice_model"])
        policy = row["policy"]
        self.assertEqual((policy["outcome"], policy["mode"], policy["level"], policy["model"]),
                         ("success", "shadow", 3, "gpt-5.6-terra"))
        self.assertIn("factor policy (shadow): level 3, model=gpt-5.6-terra", output["systemMessage"])

    def test_active_policy_replaces_the_choice(self):
        self.serve(Reply(body={"_fixture_choice_index": 0, "_factors": self.FACTORS}))
        self.write_ranked_config(policy={"mode": "active"})
        rc, out, err, _ = self.codex_hook(v2_args())
        self.assertEqual((rc, err), (0, ""))
        updated = json.loads(out)["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["model"], "gpt-5.6-terra")
        row = self.last_row()
        self.assertEqual((row["reason"], row["model"], row["policy"]["agreement"]),
                         ("policy", "gpt-5.6-terra", row["policy"]["agreement"]))
        self.assertIn("factor policy (applied)", json.loads(out)["systemMessage"])

    def test_policy_off_sends_only_the_choice(self):
        self.serve()
        self.write_config(policy={"mode": "off"})
        rc, _, err, _ = self.codex_hook(v2_args())
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(set(json.loads(self.fake.requests[0]["body"])["questions"]), {"selection"})
        self.assertNotIn("policy", self.last_row())


if __name__ == "__main__":
    unittest.main()
