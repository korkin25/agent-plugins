import unittest

from plural import choose_form, phrase

FILE = ("файл", "файла", "файлов")


class PluralTests(unittest.TestCase):
    def test_one(self):
        for n in (1, 21, 31, 1001):
            self.assertEqual(choose_form(n, FILE), "файл", n)

    def test_few(self):
        for n in (2, 3, 4, 22, 104):
            self.assertEqual(choose_form(n, FILE), "файла", n)

    def test_many(self):
        for n in (0, 5, 9, 10, 20, 25, 100):
            self.assertEqual(choose_form(n, FILE), "файлов", n)

    def test_phrase(self):
        self.assertEqual(phrase(7, ("день", "дня", "дней")), "7 дней")
        self.assertEqual(phrase(-21, FILE), "-21 файл")


if __name__ == "__main__":
    unittest.main()
