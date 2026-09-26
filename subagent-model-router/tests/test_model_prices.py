"""Offline fixtures for exact official pricing snapshots."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("router_model_prices", Path(__file__).resolve().parents[1] / "lib/router_model_prices.py")
prices = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(prices)

OPENAI = """### Standard pricing data
| Model | Short context input | Short context cached input | Short context cache writes | Short context output | Long context input | Long context cached input | Long context cache writes | Long context output |
|---|---|---|---|---|---|---|---|---|
| gpt-6-sol (<272K context length) | $2 / 1M tokens | $0.2 / 1M tokens | $2.5 / 1M tokens | $10 / 1M tokens | $4 / 1M tokens | $0.4 / 1M tokens | $5 / 1M tokens | $15 / 1M tokens |
"""
OVERVIEW = """| Feature | Fable 5.1 |
|---|---|
| Claude API ID | `claude-fable-5-1` |
| Claude API alias | `claude-fable-5-1-latest` |
"""
CLAUDE = """## Model pricing
| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
|---|---|---|---|---|---|
| Fable 5.1 | $10 / MTok | $12.50 / MTok | $20 / MTok | $0.25 / MTok | $50 / MTok |
"""

class PriceTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.cache = Path(self.root.name) / "prices.json"
        self.patch = mock.patch.object(prices, "cache_path", return_value=self.cache); self.patch.start(); self.addCleanup(self.patch.stop)

    def test_exact_official_rows_and_no_fuzzy_match(self):
        openai = prices.parse_openai(OPENAI)["gpt-6-sol"]
        self.assertEqual(openai["cached_input"], .2)
        self.assertEqual(openai["long_context"]["output"], 15)
        self.assertIn("not parsed", openai["conditions"]["conditions_note"])
        claude = prices.parse_claude(CLAUDE, OVERVIEW)["claude-fable-5-1"]
        self.assertIsNone(claude["cache_write"])
        self.assertEqual(claude["conditions"]["cache_write_5m"], 12.5)
        self.assertIn("not parsed", claude["conditions"]["conditions_note"])
        self.assertIn("claude-fable-5-1-latest", prices.parse_claude(CLAUDE, OVERVIEW))
        self.assertNotIn("fable", prices.parse_claude(CLAUDE, OVERVIEW))

    def test_refresh_read_unknown_and_stale(self):
        pages = {prices.SOURCES["codex"][0]: OPENAI}
        self.assertTrue(prices.refresh_prices("codex", ["gpt-6-sol"], fetch=pages.get, now=100))
        row = prices.cached_prices("codex", ["gpt-6-sol"], now=101)["gpt-6-sol"]
        self.assertEqual((row["input"], row["status"], row["unit"]), (2.0, "fresh", "USD/1M tokens"))
        self.assertEqual(prices.cached_prices("codex", ["gpt-6-sol-latest"], now=101)["gpt-6-sol-latest"]["status"], "unknown")
        self.assertEqual(prices.cached_prices("codex", ["gpt-6-sol"], now=100 + prices.TTL)["gpt-6-sol"]["status"], "stale")

    def test_failed_refresh_retains_stale_snapshot(self):
        pages = {prices.SOURCES["codex"][0]: OPENAI}
        self.assertTrue(prices.refresh_prices("codex", ["gpt-6-sol"], fetch=pages.get, now=100))
        self.assertFalse(prices.refresh_prices("codex", ["gpt-6-sol"], fetch=lambda _url: None, now=200, force=True))
        row = prices.cached_prices("codex", ["gpt-6-sol"], now=200)["gpt-6-sol"]
        self.assertEqual(row["retrieved_at"], 100)
        self.assertEqual(row["status"], "stale")

    def test_cold_failure_is_negative_cached_without_a_price(self):
        self.assertFalse(prices.refresh_prices("codex", ["gpt-6-unpriced"], fetch=lambda _url: None, now=100))
        row = prices.cached_prices("codex", ["gpt-6-unpriced"], now=101)["gpt-6-unpriced"]
        self.assertEqual((row["status"], row["retrieved_at"]), ("unknown", None))
        with mock.patch.object(prices.time, "time", return_value=100), \
                mock.patch.object(prices.subprocess, "Popen") as popen:
            self.assertTrue(prices.ensure_prices("codex", ["gpt-6-unpriced"]))
        popen.assert_not_called()

    def test_partial_refresh_retains_old_exact_rate_as_stale(self):
        pages = {prices.SOURCES["codex"][0]: OPENAI}
        self.assertTrue(prices.refresh_prices("codex", ["gpt-6-sol"], fetch=pages.get, now=100))
        with mock.patch.object(prices, "parse_openai", return_value={}):
            self.assertFalse(prices.refresh_prices("codex", ["gpt-6-new"], fetch=pages.get, now=200, force=True))
        self.assertEqual(prices.cached_prices("codex", ["gpt-6-sol"], now=200)["gpt-6-sol"]["status"], "stale")

    def test_cold_failure_preserves_other_agent_snapshot(self):
        codex_pages = {prices.SOURCES["codex"][0]: OPENAI}
        claude_pages = {url: "not a pricing table" for url in prices.SOURCES["claude"]}
        for fetch in (lambda _url: None, claude_pages.get):
            with self.subTest(fetch=fetch):
                self.cache.unlink(missing_ok=True)
                self.assertTrue(prices.refresh_prices("codex", ["gpt-6-sol"], fetch=codex_pages.get, now=100))
                self.assertFalse(prices.refresh_prices("claude", ["claude-cold"], fetch=fetch, now=200))
                row = prices.cached_prices("codex", ["gpt-6-sol"], now=201)["gpt-6-sol"]
                self.assertEqual((row["input"], row["status"], row["retrieved_at"]), (2.0, "fresh", 100))

if __name__ == "__main__": unittest.main()
