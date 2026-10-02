#!/usr/bin/env python3
"""Hidden tests for code-05; the subagent never sees this file.

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
MODULE = "brackets"


def run(module):
    fixed = [
        ("empty", ""),
        ("no-brackets", "plain text, no brackets at all"),
        ("simple-pairs", "()[]{}"),
        ("nested", "{[()()]}"),
        ("crossed", "([)]"),
        ("crossed-late", "(a)[b]{c(d]e}"),
        ("closer-first", "]()"),
        ("extra-closer-end", "(())))"),
        ("unclosed-single", "abc("),
        ("unclosed-nested", "((x)(y"),
        ("unclosed-outer-only", "[{}()"),
        ("unclosed-several-kinds", "{ [ ( ) "),
        ("mismatch-after-unclosed", "(((]"),
        ("closer-of-other-kind", "(}"),
        ("deep-balanced", "(" * 300 + "[]" + ")" * 300),
        ("deep-unclosed", "(" * 300 + ")" * 299),
        ("non-ascii-before", "ключ: значение (вложенное [x]) é"),
        ("non-ascii-error", "日本(語]"),
        ("angle-ignored", "<(>)"),
        ("quotes-ignored", "\"(\" + ')'"),
    ]
    for name, text in fixed:
        yield name, attempt(module.first_error, text)
    rng = random.Random(20261005)
    alphabet = "()[]{}" * 3 + "ab "
    for index in range(150):
        length = rng.randint(1, 24)
        if index % 3 == 0:
            pieces = []
            for _ in range(length // 2):
                opener, closer = rng.choice(["()", "[]", "{}"])
                position = rng.randint(0, len(pieces))
                pieces.insert(position, opener)
                pieces.insert(rng.randint(position + 1, len(pieces)), closer)
            text = "".join(pieces)
            if text and index % 2 == 0:
                cut = rng.randrange(len(text))
                text = text[:cut] + text[cut + 1:]
        else:
            text = "".join(rng.choice(alphabet) for _ in range(length))
        yield f"random-{index}", attempt(module.first_error, text)


if __name__ == "__main__":
    sys.exit(main())
