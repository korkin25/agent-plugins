import unittest

from roman import to_roman


class ToRomanTests(unittest.TestCase):
    def test_small_numbers(self):
        self.assertEqual([to_roman(n) for n in range(1, 11)],
                         ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"])

    def test_tens_and_hundreds(self):
        self.assertEqual(to_roman(90), "XC")
        self.assertEqual(to_roman(500), "D")
        self.assertEqual(to_roman(1987), "MCMLXXXVII")
        self.assertEqual(to_roman(3999), "MMMCMXCIX")

    def test_out_of_range(self):
        for bad in (0, 4000, -5):
            with self.assertRaises(ValueError):
                to_roman(bad)


if __name__ == "__main__":
    unittest.main()
