import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ttlcache import TTLCache  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class VisibleTests(unittest.TestCase):
    def test_lru_eviction(self):
        cache = TTLCache(2, 100, clock=FakeClock())
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        cache.put("c", 3)
        self.assertEqual(cache.keys(), ["a", "c"])

    def test_expiry(self):
        clock = FakeClock()
        cache = TTLCache(5, 10, clock=clock)
        cache.put("a", 1)
        clock.now = 9.5
        self.assertIn("a", cache)
        clock.now = 10
        self.assertNotIn("a", cache)
        self.assertEqual(cache.get("a", "missing"), "missing")

    def test_bad_capacity(self):
        with self.assertRaises(ValueError):
            TTLCache(0, 1)


if __name__ == "__main__":
    unittest.main()
