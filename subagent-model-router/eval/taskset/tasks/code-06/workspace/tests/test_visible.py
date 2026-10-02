import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roman import from_roman, to_roman  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_to_roman(self):
        self.assertEqual(to_roman(1994), "MCMXCIV")

    def test_from_roman(self):
        self.assertEqual(from_roman("XLII"), 42)

    def test_non_canonical_rejected(self):
        with self.assertRaises(ValueError):
            from_roman("IIII")


if __name__ == "__main__":
    unittest.main()
