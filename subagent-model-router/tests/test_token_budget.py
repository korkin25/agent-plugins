"""Offline tests for visible-task token and input-cost estimates."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("router_token_budget", Path(__file__).resolve().parents[1] / "lib/router_token_budget.py")
budget = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(budget)


class TokenBudgetTests(unittest.TestCase):
    def test_visible_task_uses_full_filtered_cyrillic_and_code_text(self):
        state = {"description": "Проверить код", "task": "def f():\n    return 'ok'"}
        result = budget.estimated_request(state)
        visible = result["visible_task"]
        raw = (state["description"] + state["task"]).encode("utf-8")
        self.assertEqual((visible["characters"], visible["utf8_bytes"]),
                         (len(state["description"] + state["task"]), len(raw)))
        self.assertEqual(visible["input_tokens_estimate"], (len(raw) + 3) // 4)
        self.assertEqual((visible["scope"], visible["method"], visible["approximate"]),
                         (budget.SCOPE, budget.METHOD, True))
        self.assertEqual(result["native_child_prompt"]["status"], "unknown")

    def test_empty_visible_task_is_zero_and_bad_state_is_unavailable(self):
        self.assertEqual(budget.estimated_request({"description": "", "task": ""})["visible_task"]["input_tokens_estimate"], 0)
        self.assertIsNone(budget.estimated_request({"description": "only one field"}))

    def test_fresh_and_stale_prices_keep_provenance_and_context_bands_separate(self):
        request = budget.estimated_request({"description": "", "task": "abcd"})
        price = {"status": "stale", "retrieved_at": 100, "source_url": "https://official.example/pricing",
                 "input": 2, "long_context": {"input": 5}}
        result = budget.estimate_input_cost(request, price)
        self.assertEqual((result["price_status"], result["price_retrieved_at"], result["price_source_url"]),
                         ("stale", 100, "https://official.example/pricing"))
        self.assertEqual((result["uncached_input_usd_estimate"], result["long_context_uncached_input_usd_estimate"]),
                         (2 / 1_000_000, 5 / 1_000_000))
        self.assertEqual((result["cache_assumption"], result["context_band"]), ("uncached_input", "unknown"))

    def test_unknown_or_invalid_rates_never_become_zero_cost(self):
        request = budget.estimated_request({"description": "", "task": "abcd"})
        for price in ({"status": "unknown", "input": 0}, {"status": "fresh", "input": None},
                      {"status": "fresh", "input": float("nan")}, {"status": "fresh", "input": -1}):
            with self.subTest(price=price):
                result = budget.estimate_input_cost(request, price)
                self.assertIsNone(result["uncached_input_usd_estimate"])

    def test_repeated_efforts_do_not_change_the_single_task_estimate(self):
        request = budget.estimated_request({"description": "d", "task": "task"})
        price = {"status": "fresh", "retrieved_at": 1, "source_url": "https://official.example/pricing", "input": 4}
        low, high = budget.estimate_input_cost(request, price), budget.estimate_input_cost(request, price)
        self.assertEqual(low["input_tokens_estimate"], high["input_tokens_estimate"])
        self.assertEqual(low["uncached_input_usd_estimate"], high["uncached_input_usd_estimate"])


if __name__ == "__main__":
    unittest.main()
