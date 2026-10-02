"""Word frequencies of a text."""


def top_words(text, k):
    """Return the ``k`` most frequent words of ``text`` with their counts.

    A word is a maximal run of ASCII letters ``A``-``Z`` and ``a``-``z``; every other character (digits, spaces,
    punctuation, apostrophes, any non-ASCII character) separates words. Words are counted case-insensitively and
    reported in lower case: ``"Tea"``, ``"TEA"`` and ``"tea"`` are the same word ``"tea"``.

    The result is a list of ``(word, count)`` tuples ordered by count, highest first; words with equal counts are
    ordered alphabetically (plain string order of the lower-case words). It holds the first ``k`` entries of that
    order, or all of them if there are fewer than ``k`` distinct words. ``k <= 0`` gives ``[]``, and so does a text
    without words.
    """
    raise NotImplementedError
