import unittest

from stats import summarize


class SummarizeTests(unittest.TestCase):
    def test_odd_count(self):
        self.assertEqual(summarize([70, 50, 90]),
                         {"count": 3, "mean": 70.0, "median": 70, "min": 50, "max": 90})

    def test_even_count(self):
        result = summarize((10, 40, 20, 30))
        self.assertEqual(result["median"], 25.0)
        self.assertEqual(result["mean"], 25.0)

    def test_empty(self):
        with self.assertRaises(ValueError):
            summarize([])


if __name__ == "__main__":
    unittest.main()
