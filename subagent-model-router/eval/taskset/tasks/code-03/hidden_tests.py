#!/usr/bin/env python3
"""Hidden tests for code-03; the subagent never sees this file.

check.py runs `python3 -I -B hidden_tests.py CODE_DIR OUT_JSON` twice: on the reference in solution/ and on the
subagent's copy. Each run imports the module from CODE_DIR, runs every case below and writes one JSON result per
case to OUT_JSON; check.py compares the two lists, so every expected value is produced by the reference.
"""
import json
import random
import sys
from pathlib import Path


def canon(value, depth=0):
    """A JSON-able form of a value: tuples and lists alike, dict keys in any order, other objects by type name."""
    if depth > 60:
        return "<too deep>"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else repr(value)
    if isinstance(value, (list, tuple)):
        return [canon(item, depth + 1) for item in value]
    if isinstance(value, dict):
        pairs = [[canon(k, depth + 1), canon(v, depth + 1)] for k, v in value.items()]
        return {"<dict>": sorted(pairs, key=lambda pair: json.dumps(pair, ensure_ascii=False))}
    return f"<{type(value).__name__}>"


def attempt(func, *args, **kwargs):
    """Call func and describe the outcome: a value, a ValueError, or any other exception by its type."""
    try:
        return {"value": canon(func(*args, **kwargs))}
    except ValueError:
        return {"raises": "ValueError"}
    except Exception as exc:  # noqa: BLE001 - any other failure of the code under test
        return {"error": type(exc).__name__}


def main() -> int:
    code, out = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(code))
    module = __import__(MODULE)
    results = [{"case": name, "result": outcome} for name, outcome in run(module)]
    out.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return 0


# ---- task-specific cases ----------------------------------------------------------------------------------
MODULE = "spiral"


def grid(rows, cols, start=1):
    return [[start + r * cols + c for c in range(cols)] for r in range(rows)]


def call(module, matrix):
    argument = [list(row) for row in matrix]
    outcome = attempt(module.spiral_order, argument)
    outcome["argument_after"] = canon(argument)
    return outcome


def run(module):
    fixed = {
        "empty": [],
        "one-empty-row": [[]],
        "two-empty-rows": [[], []],
        "one-element": [[7]],
        "one-row": [[1, 2, 3, 4, 5]],
        "one-column": [[1], [2], [3], [4]],
        "two-by-two": grid(2, 2),
        "three-by-three": grid(3, 3),
        "two-by-four": grid(2, 4),
        "four-by-two": grid(4, 2),
        "three-by-five": grid(3, 5),
        "five-by-three": grid(5, 3),
        "three-by-four": grid(3, 4),
        "four-by-three": grid(4, 3),
        "five-by-five": grid(5, 5),
        "six-by-one": grid(6, 1),
        "one-by-six": grid(1, 6),
        "strings": [["a", "b"], ["c", "d"], ["e", "f"]],
        "repeated-values": [[0, 0, 0], [0, 1, 0]],
        "ragged-short-last": [[1, 2, 3], [4, 5]],
        "ragged-long-last": [[1], [2, 3]],
        "ragged-empty-row": [[1, 2], []],
    }
    for name, matrix in fixed.items():
        yield name, call(module, matrix)
    for rows in range(1, 9):
        for cols in range(1, 9):
            yield f"grid-{rows}x{cols}", call(module, grid(rows, cols, start=rows * 100))


if __name__ == "__main__":
    sys.exit(main())
