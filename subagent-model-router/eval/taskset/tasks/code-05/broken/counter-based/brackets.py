"""Find the first bracket error in a piece of text."""

PAIRS = {")": "(", "]": "[", "}": "{"}
OPENERS = set(PAIRS.values())


def first_error(text):
    """Return the position of the first bracket error in ``text``, or ``-1`` if its brackets are balanced.

    Only the six characters ``( ) [ ] { }`` are brackets; every other character is ignored. Brackets are balanced
    when every closer matches the nearest still-open opener of the same kind, in the usual nested way:
    ``"a(b[c]{d})"`` is balanced, ``"([)]"`` is not.

    Scan ``text`` from left to right:

    * the first closer that has no open opener, or whose kind differs from the most recently opened unclosed
      bracket, is the error, and its index is returned;
    * if the scan reaches the end with no such closer but some openers are still unclosed, the error is the
      leftmost opener that is never closed, and its index is returned.

    Indices are ordinary ``str`` indices of ``text``. The empty string and text without brackets are balanced.
    """
    open_positions = {opener: [] for opener in OPENERS}
    for index, char in enumerate(text):
        if char in OPENERS:
            open_positions[char].append(index)
        elif char in PAIRS:
            if not open_positions[PAIRS[char]]:
                return index
            open_positions[PAIRS[char]].pop()
    unclosed = [position for positions in open_positions.values() for position in positions]
    return min(unclosed) if unclosed else -1
