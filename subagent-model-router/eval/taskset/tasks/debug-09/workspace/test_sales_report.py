import unittest
from decimal import Decimal

from sales_report import report, summarize


def sale(region, amount):
    return {"date": "2026-09-01", "region": region, "amount": Decimal(amount)}


class SalesReportTests(unittest.TestCase):
    def test_summarize(self):
        rows = [sale("East", "10.00"), sale("East", "5.50"), sale("North", "7.25")]
        self.assertEqual(summarize(rows), [("East", 2, Decimal("15.50")), ("North", 1, Decimal("7.25"))])

    def test_sorted_by_region(self):
        rows = [sale("West", "1.00"), sale("East", "2.00")]
        self.assertEqual([region for region, _, _ in summarize(rows)], ["East", "West"])

    def test_report(self):
        rows = [sale("East", "30.00"), sale("West", "10.00")]
        self.assertEqual(report(rows), ["East  1  30.00  75.0%", "West  1  10.00  25.0%", "TOTAL  2  40.00"])


if __name__ == "__main__":
    unittest.main()
