import unittest
from datetime import date

from workdays import add_business_days, is_business_day


class WorkdaysTests(unittest.TestCase):
    def test_within_a_week(self):
        self.assertEqual(add_business_days(date(2026, 10, 5), 1), date(2026, 10, 6))
        self.assertEqual(add_business_days(date(2026, 10, 5), 4), date(2026, 10, 9))

    def test_from_friday(self):
        self.assertEqual(add_business_days(date(2026, 10, 9), 1), date(2026, 10, 12))

    def test_zero(self):
        self.assertEqual(add_business_days(date(2026, 10, 10), 0), date(2026, 10, 10))

    def test_is_business_day(self):
        self.assertTrue(is_business_day(date(2026, 10, 2)))
        self.assertFalse(is_business_day(date(2026, 10, 3)))
        self.assertFalse(is_business_day(date(2026, 10, 2), {date(2026, 10, 2)}))


if __name__ == "__main__":
    unittest.main()
