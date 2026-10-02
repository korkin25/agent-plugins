"""Durations written as compact unit strings such as ``"1h30m"`` or ``"2d 4h"``.

Units and their lengths in seconds:

    w  week    604800
    d  day      86400
    h  hour      3600
    m  minute      60
    s  second       1

There are no months or years; ``m`` always means minutes.
"""

UNITS = [("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
ORDER = [unit for unit, _ in UNITS]
LENGTH = dict(UNITS)
DIGITS = "0123456789"


def parse_duration(text):
    """Return the number of seconds described by ``text``.

    ``text`` is a sequence of one or more components. A component is one or more ASCII digits ``0``-``9``
    immediately followed by a lower-case unit letter, e.g. ``"90m"`` or ``"007s"``; nothing may stand between the
    number and its unit. Each unit appears at most once, and the components appear in decreasing unit order
    (``w`` before ``d`` before ``h`` before ``m`` before ``s``). Components may be written next to each other or
    separated by whitespace, and leading and trailing whitespace is allowed; whitespace means characters for which
    ``str.isspace()`` is true. Numbers have no upper limit and zero is allowed (``"0s"`` is 0).

    Any other input raises ``ValueError``: the empty or all-whitespace string, a number without a unit, a unit
    without a number, unknown or upper-case units, signs, decimal points, repeated units, units out of order, and
    digits other than ``0``-``9``.
    """
    import re

    match = re.fullmatch(r"\s*(?:(\d+)w\s*)?(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s\s*)?", text)
    if match is None or not any(match.groups()):
        raise ValueError(f"not a duration: {text!r}")
    return sum(int(number) * length for number, (_, length) in zip(match.groups(), UNITS) if number)


def format_duration(seconds):
    """Return the canonical text for a duration of ``seconds`` seconds.

    ``seconds`` must be a non-negative ``int``; a negative value raises ``ValueError``. The result lists the
    non-zero components from the largest unit to the smallest, each as a decimal number without leading zeros
    followed by its unit, with no spaces, using as many whole weeks as possible, then days, and so on: 3661 gives
    ``"1h1m1s"`` and 694861 gives ``"1w1d1h1m1s"``. Zero gives ``"0s"``. ``parse_duration`` of the result is
    ``seconds`` again.
    """
    if seconds < 0:
        raise ValueError(f"negative duration: {seconds!r}")
    parts = []
    for unit, length in UNITS:
        count, seconds = divmod(seconds, length)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts) or "0s"
