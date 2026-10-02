import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from toposort import CycleError, topo_order  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_smallest_order(self):
        self.assertEqual(topo_order(["c", "b", "a"], [("c", "a")]), ["b", "c", "a"])

    def test_cycle(self):
        with self.assertRaises(CycleError) as caught:
            topo_order(["x", "y"], [("x", "y"), ("y", "x")])
        self.assertIn(caught.exception.cycle, (["x", "y", "x"], ["y", "x", "y"]))

    def test_unknown_node(self):
        with self.assertRaises(ValueError):
            topo_order(["a"], [("a", "b")])


if __name__ == "__main__":
    unittest.main()
