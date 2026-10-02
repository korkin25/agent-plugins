import unittest

from wrap import paragraphs, wrap


class WrapTests(unittest.TestCase):
    def test_fills_greedily(self):
        self.assertEqual(wrap("the quick brown fox jumps over the lazy dog", 15),
                         ["the quick brown", "fox jumps over", "the lazy dog"])

    def test_long_word_stays_whole(self):
        self.assertEqual(wrap("a extraordinarily b", 6), ["a", "extraordinarily", "b"])

    def test_first_prefix(self):
        self.assertEqual(wrap("one two", 20, first_prefix="* "), ["* one two"])

    def test_paragraphs(self):
        self.assertEqual(paragraphs("a b\nc\n\n\nd\n"), ["a b c", "d"])


if __name__ == "__main__":
    unittest.main()
