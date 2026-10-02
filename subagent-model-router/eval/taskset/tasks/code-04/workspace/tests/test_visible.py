import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wordfreq import top_words  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_counts_case_insensitively(self):
        self.assertEqual(top_words("Tea tea TEA coffee. Coffee? water", 2), [("tea", 3), ("coffee", 2)])

    def test_fewer_words_than_k(self):
        self.assertEqual(top_words("one two two", 10), [("two", 2), ("one", 1)])

    def test_zero_k(self):
        self.assertEqual(top_words("anything at all", 0), [])


if __name__ == "__main__":
    unittest.main()
