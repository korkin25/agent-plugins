"""Reading score files: one result per line, `NAME SCORE`, where SCORE is a whole number from 0 to 100.

Blank lines and lines starting with # are skipped. The files can be large, so they are read lazily.
"""


class ScoreError(ValueError):
    pass


def read_scores(path: str):
    """Yield the scores of the file at `path` one at a time, in file order, as ints.

    ScoreError for a line that is not `NAME SCORE` with a whole SCORE from 0 to 100; the message names the line
    number.
    """
    return list(_read(path))


def _read(path):
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) > 100:
                raise ScoreError(f"line {number}: expected NAME SCORE, got {line!r}")
            yield int(parts[1])
