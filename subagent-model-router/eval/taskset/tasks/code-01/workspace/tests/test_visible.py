import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intervals import merge_intervals  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_overlapping(self):
        self.assertEqual(merge_intervals([(1, 4), (2, 6), (8, 10)]), [(1, 6), (8, 10)])

    def test_unsorted_input(self):
        self.assertEqual(merge_intervals([(20, 25), (1, 2), (10, 12)]), [(1, 2), (10, 12), (20, 25)])

    def test_nested(self):
        self.assertEqual(merge_intervals([(0, 100), (5, 7)]), [(0, 100)])


if __name__ == "__main__":
    unittest.main()
