#!/usr/bin/env python3
"""Hidden tests for code-04; the subagent never sees this file.

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
MODULE = "wordfreq"

VOCABULARY = ["ash", "birch", "cedar", "Elm", "fir", "hazel", "larch", "maple", "oak", "pine", "rowan", "yew"]
SEPARATORS = [" ", "  ", ", ", ". ", "\n", "\t", "-", "/", "1", "42", "; ", "!", "_", "(", ") "]


def run(module):
    fixed = [
        ("ties-alphabetical", "pear apple fig pear apple fig kiwi", 3),
        ("ties-first-seen-last", "zebra yak xenops zebra yak xenops", 2),
        ("ties-cut-at-k", "delta charlie bravo alpha", 2),
        ("punctuation-joined", "north,south;east.west north/south", 10),
        ("digits-split", "abc123def abc 9abc9", 5),
        ("apostrophes", "it's the cat's toy, isn't it", 10),
        ("underscores-and-hyphens", "snake_case kebab-case snake case", 10),
        ("mixed-case", "Rain RAIN rain rAIn Sun", 5),
        ("empty", "", 3),
        ("no-words", "123 456 --- !!!", 3),
        ("negative-k", "a b c", -1),
        ("k-one", "b a b a c", 1),
        ("non-ascii-separates", "café naïve über", 10),
        ("newlines-and-tabs", "one\ttwo\nthree\r\ntwo\none", 10),
        ("single-letters", "a A b B b c", 10),
        ("long-text", ("the quick brown fox jumps over the lazy dog " * 7 + "The END the end") * 3, 4),
    ]
    for name, text, k in fixed:
        yield name, attempt(module.top_words, text, k)
    rng = random.Random(20261004)
    for index in range(40):
        parts = []
        for _ in range(rng.randint(0, 60)):
            word = rng.choice(VOCABULARY)
            if rng.random() < 0.3:
                word = word.upper() if rng.random() < 0.5 else word.capitalize()
            parts.append(word)
            parts.append(rng.choice(SEPARATORS))
        yield f"random-{index}", attempt(module.top_words, "".join(parts), rng.randint(-1, 14))


if __name__ == "__main__":
    sys.exit(main())
