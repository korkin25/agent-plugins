import unittest

from pager import get_page, page_count


class PagerTests(unittest.TestCase):
    def test_full_pages(self):
        self.assertEqual(page_count(30, 10), 3)
        self.assertEqual(page_count(4, 1), 4)

    def test_get_page(self):
        items = list(range(1, 21))
        self.assertEqual(get_page(items, 1, 10), list(range(1, 11)))
        self.assertEqual(get_page(items, 2, 10), list(range(11, 21)))

    def test_no_such_page(self):
        with self.assertRaises(IndexError):
            get_page(list(range(20)), 3, 10)
        with self.assertRaises(IndexError):
            get_page(list(range(20)), 0, 10)


if __name__ == "__main__":
    unittest.main()
