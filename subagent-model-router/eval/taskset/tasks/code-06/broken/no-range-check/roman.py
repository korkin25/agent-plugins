"""Roman numerals in their standard (canonical) form.

The canonical form writes thousands, hundreds, tens and units in that order, each with the usual symbols
``I V X L C D M`` (values 1, 5, 10, 50, 100, 500, 1000) and the subtractive pairs ``IV IX XL XC CD CM``:

    1 I, 2 II, 3 III, 4 IV, 5 V, 6 VI, 7 VII, 8 VIII, 9 IX   (and likewise for tens with X L C,
    hundreds with C D M, thousands with M only: M, MM, MMM).

So 1994 is ``"MCMXCIV"`` and 3999 is ``"MMMCMXCIX"``. Only upper-case letters are used.
"""

SYMBOLS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]
LETTERS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def to_roman(n):
    """Return the canonical Roman numeral for ``n``.

    ``n`` must be an ``int`` from 1 to 3999 inclusive; any other value raises ``ValueError``.
    """
    parts = []
    for value, symbol in SYMBOLS:
        count, n = divmod(n, value)
        parts.append(symbol * count)
    return "".join(parts)


def from_roman(s):
    """Return the value of the Roman numeral ``s``.

    Only canonical numerals are accepted: ``s`` must be exactly the string that ``to_roman`` returns for some
    value from 1 to 3999. Anything else raises ``ValueError``, including non-canonical spellings such as
    ``"IIII"`` or ``"IC"``, lower-case letters, surrounding whitespace and the empty string.
    """
    if not isinstance(s, str) or not s or any(char not in LETTERS for char in s):
        raise ValueError(f"not a Roman numeral: {s!r}")
    total = 0
    for index, char in enumerate(s):
        value = LETTERS[char]
        if index + 1 < len(s) and LETTERS[s[index + 1]] > value:
            total -= value
        else:
            total += value
    if to_roman(total) != s:
        raise ValueError(f"not a canonical Roman numeral: {s!r}")
    return total
