import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luhn import check_digit, is_valid  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_valid_number(self):
        self.assertTrue(is_valid("79927398713"))

    def test_invalid_number(self):
        self.assertFalse(is_valid("79927398710"))

    def test_spaces_are_ignored(self):
        self.assertTrue(is_valid("7992 7398 713"))

    def test_check_digit(self):
        self.assertEqual(check_digit("7992739871"), "3")


if __name__ == "__main__":
    unittest.main()
