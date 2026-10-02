"""Roman numerals in their standard (canonical) form.

The canonical form writes thousands, hundreds, tens and units in that order, each with the usual symbols
``I V X L C D M`` (values 1, 5, 10, 50, 100, 500, 1000) and the subtractive pairs ``IV IX XL XC CD CM``:

    1 I, 2 II, 3 III, 4 IV, 5 V, 6 VI, 7 VII, 8 VIII, 9 IX   (and likewise for tens with X L C,
    hundreds with C D M, thousands with M only: M, MM, MMM).

So 1994 is ``"MCMXCIV"`` and 3999 is ``"MMMCMXCIX"``. Only upper-case letters are used.
"""


def to_roman(n):
    """Return the canonical Roman numeral for ``n``.

    ``n`` must be an ``int`` from 1 to 3999 inclusive; any other value raises ``ValueError``.
    """
    raise NotImplementedError


def from_roman(s):
    """Return the value of the Roman numeral ``s``.

    Only canonical numerals are accepted: ``s`` must be exactly the string that ``to_roman`` returns for some
    value from 1 to 3999. Anything else raises ``ValueError``, including non-canonical spellings such as
    ``"IIII"`` or ``"IC"``, lower-case letters, surrounding whitespace and the empty string.
    """
    raise NotImplementedError
