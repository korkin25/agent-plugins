import unittest

from pricebook import first_above, in_range

PRICES = [199, 250, 250, 999, 1200, 1200, 1200, 4500]


class PricebookTests(unittest.TestCase):
    def test_first_above(self):
        self.assertEqual(first_above(PRICES, 250), 3)
        self.assertEqual(first_above(PRICES, 100), 0)
        self.assertEqual(first_above(PRICES, 4500), 8)

    def test_range_from_the_bottom(self):
        self.assertEqual(in_range(PRICES, 0, 250), [199, 250, 250])
        self.assertEqual(in_range(PRICES, 199, 199), [199])

    def test_empty_list(self):
        self.assertEqual(in_range([], 0, 100), [])


if __name__ == "__main__":
    unittest.main()
