import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autocomplete import Autocomplete  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_ranking(self):
        ac = Autocomplete()
        ac.add("кот", 3)
        ac.add("кофе", 5)
        ac.add("кол")
        self.assertEqual(ac.complete("ко"), ["кофе", "кот", "кол"])

    def test_weights_accumulate(self):
        ac = Autocomplete()
        ac.add("дом")
        ac.add("дом", 2)
        self.assertEqual(ac.score("дом"), 3)
        self.assertEqual(len(ac), 1)

    def test_remove(self):
        ac = Autocomplete()
        ac.add("лес")
        self.assertTrue(ac.remove("лес"))
        self.assertFalse(ac.remove("лес"))
        self.assertEqual(ac.complete(""), [])


if __name__ == "__main__":
    unittest.main()
