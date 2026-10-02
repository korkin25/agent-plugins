import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brackets import first_error  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_balanced(self):
        self.assertEqual(first_error("f(a[0], {b: c})"), -1)

    def test_closer_without_opener(self):
        self.assertEqual(first_error("x)"), 1)

    def test_empty(self):
        self.assertEqual(first_error(""), -1)


if __name__ == "__main__":
    unittest.main()
