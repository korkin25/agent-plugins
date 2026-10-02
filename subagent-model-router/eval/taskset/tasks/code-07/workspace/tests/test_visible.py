import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from durations import format_duration, parse_duration  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration(" 2d 4h "), 187200)

    def test_parse_rejects_unknown_unit(self):
        with self.assertRaises(ValueError):
            parse_duration("3y")

    def test_format(self):
        self.assertEqual(format_duration(3661), "1h1m1s")


if __name__ == "__main__":
    unittest.main()
