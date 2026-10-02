import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expenses import BadAmount, totals


def csv_file(text):
    folder = Path(tempfile.mkdtemp())
    path = folder / "expenses.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TotalsTests(unittest.TestCase):
    def test_total(self):
        path = csv_file("category,amount\nfood,10.50\nrent,400\nfood,-0.50\n")
        self.assertEqual(totals(path), {"total": Decimal("410.00")})

    def test_by_category(self):
        path = csv_file("category,amount\nfood,10.50\nrent,400\nfood,2\n")
        self.assertEqual(totals(path, by="category"), {"food": Decimal("12.50"), "rent": Decimal("400")})

    def test_bad_amount(self):
        path = csv_file("category,amount\nfood,10.50\nrent,four hundred\n")
        with self.assertRaises(BadAmount) as caught:
            totals(path)
        self.assertIn("line 3", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
