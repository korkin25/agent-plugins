#!/usr/bin/env python3
"""Hidden tests for code-01; the subagent never sees this file.

check.py runs `python3 -I -B hidden_tests.py CODE_DIR OUT_JSON` twice: on the reference in solution/ and on the
subagent's copy. Each run imports the module from CODE_DIR, runs every case below and writes one JSON result per
case to OUT_JSON; check.py compares the two lists, so every expected value is produced by the reference.
"""
import json
import random
import sys
from pathlib import Path


def canon(value, depth=0):
    """A JSON-able form of a value: a tuple tagged apart from a list, dict keys in any order, others by type name."""
    if depth > 60:
        return "<too deep>"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else repr(value)
    if isinstance(value, tuple):
        return {"<tuple>": [canon(item, depth + 1) for item in value]}
    if isinstance(value, list):
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
MODULE = "intervals"


def call(module, intervals):
    """Merge a private copy; report the result, the argument as it is afterwards and whether it came back itself."""
    argument = [tuple(pair) if isinstance(pair, tuple) else list(pair) for pair in intervals]
    returned = []

    def merge(value):
        result = module.merge_intervals(value)
        returned.append(result is value)
        return result

    outcome = attempt(merge, argument)
    outcome["argument_after"] = canon(argument)
    if returned and returned[0]:
        outcome["returned_the_argument"] = True
    return outcome


def run(module):
    fixed = {
        "empty": [],
        "single": [(3, 7)],
        "single-list": [[3, 7]],
        "point": [(5, 5)],
        "touching": [(1, 3), (3, 5)],
        "touching-chain": [(7, 9), (1, 3), (5, 7), (3, 5)],
        "adjacent-not-touching": [(1, 3), (4, 5)],
        "gap-of-one": [(1, 2), (4, 6), (8, 8)],
        "duplicates": [(2, 4), (2, 4), (2, 4)],
        "nested": [(1, 10), (2, 3), (4, 9), (5, 5)],
        "reverse-sorted": [(9, 12), (6, 8), (3, 5), (0, 2)],
        "chain-overlap": [(1, 5), (4, 8), (7, 11), (10, 14)],
        "negative": [(-10, -5), (-5, 0), (2, 3), (-20, -15)],
        "same-start": [(1, 2), (1, 9), (1, 4)],
        "lists-not-tuples": [[4, 6], [1, 2], [2, 3]],
        "large-values": [(10**18, 10**18 + 5), (-(10**18), 10**18 - 1), (10**18 + 5, 10**18 + 9)],
        "unsorted-overlap": [(5, 6), (1, 5), (6, 10), (12, 13)],
        "invalid": [(1, 3), (5, 4)],
        "invalid-only": [(2, 1)],
    }
    for name, intervals in fixed.items():
        yield name, call(module, intervals)
    rng = random.Random(20261001)
    for index in range(40):
        size = rng.randint(0, 30)
        intervals = []
        for _ in range(size):
            start = rng.randint(-50, 50)
            intervals.append((start, start + rng.randint(0, 8)))
        yield f"random-{index}", call(module, intervals)


if __name__ == "__main__":
    sys.exit(main())
