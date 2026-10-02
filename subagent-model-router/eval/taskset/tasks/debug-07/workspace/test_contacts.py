import tempfile
import unittest
from pathlib import Path

from contacts import FormatError, check_header, load, read_header


def csv_file(text):
    path = Path(tempfile.mkdtemp()) / "contacts.csv"
    path.write_text(text, encoding="utf-8")
    return path


class ContactsTests(unittest.TestCase):
    def test_load(self):
        path = csv_file("name,email,city\nАнна,anna@example.org,Казань\n\nБорис,boris@example.org,Тверь\n")
        self.assertEqual(load(path), [
            {"name": "Анна", "email": "anna@example.org", "city": "Казань"},
            {"name": "Борис", "email": "boris@example.org", "city": "Тверь"},
        ])

    def test_columns_in_any_order(self):
        path = csv_file("city, email ,phone,name\nОмск,vera@example.org,,Вера\n")
        self.assertEqual(load(path), [{"name": "Вера", "email": "vera@example.org", "city": "Омск"}])

    def test_missing_columns(self):
        with self.assertRaises(FormatError) as caught:
            check_header(["name", "phone"])
        self.assertEqual(str(caught.exception), "нет колонок: email, city")

    def test_read_header(self):
        self.assertEqual(read_header(csv_file(" name ,email,city\n")), ["name", "email", "city"])


if __name__ == "__main__":
    unittest.main()
