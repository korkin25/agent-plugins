import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miniini import parse_ini  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_basic(self):
        text = "; settings\n[server]\nHost = example.org\nport=8080\n\n[client]\nretries = 3\n"
        self.assertEqual(parse_ini(text), {"server": {"host": "example.org", "port": "8080"},
                                           "client": {"retries": "3"}})

    def test_continuation(self):
        self.assertEqual(parse_ini("[s]\nmotd = hello\n  world\n"), {"s": {"motd": "hello\nworld"}})

    def test_key_before_section(self):
        with self.assertRaises(ValueError):
            parse_ini("a = 1\n")


if __name__ == "__main__":
    unittest.main()
