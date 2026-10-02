import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spiral import spiral_order  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_square(self):
        self.assertEqual(spiral_order([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), [1, 2, 3, 6, 9, 8, 7, 4, 5])

    def test_four_by_four(self):
        matrix = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]]
        self.assertEqual(spiral_order(matrix), [1, 2, 3, 4, 8, 12, 16, 15, 14, 13, 9, 5, 6, 7, 11, 10])

    def test_ragged_rows(self):
        with self.assertRaises(ValueError):
            spiral_order([[1, 2], [3]])


if __name__ == "__main__":
    unittest.main()
