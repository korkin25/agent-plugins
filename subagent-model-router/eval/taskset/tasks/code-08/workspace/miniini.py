"""A small INI dialect."""


def parse_ini(text):
    r"""Parse ``text`` in the mini-INI dialect below and return ``{section: {key: value}}``.

    Lines are separated by ``"\n"`` only; one ``"\r"`` at the end of a line is removed first, so ``"\r\n"``
    endings work. No other character ends a line. "Whitespace" means characters for which ``str.isspace()``
    is true, and "stripped" means ``str.strip()`` with no argument. Each line is exactly one of these kinds,
    tested in this order:

    1. Blank line - empty or only whitespace. Ignored.
    2. Comment - the first character is ``;`` or ``#``. Ignored.
    3. Continuation - the first character is whitespace. It extends the value of the key defined on the
       line just before it: the value gets ``"\n"`` plus the stripped line appended. The line just before
       must be a key line or another continuation line; otherwise (first line, after a blank line, after a
       comment, after a section header) it is an error.
    4. Section header - the first character is ``[``. With trailing whitespace removed the line must end with
       ``]``; the section name is the stripped text between the brackets and must not be empty. Names are
       case-sensitive. A section that appears again continues the earlier one: its keys are added to the same
       dictionary. A section without keys still appears in the result with an empty dictionary.
    5. Key line - contains ``=``. The key is the text before the first ``=``, stripped and lower-cased with
       ``str.lower()``, and must not be empty; the value is everything after the first ``=``, stripped (it may
       be empty and may contain further ``=``). A key line must come after a section header. If a key appears
       again in the same section, the later value replaces the earlier one.
    6. Anything else is an error.

    Every error raises ``ValueError``. An empty text gives ``{}``.
    """
    raise NotImplementedError
