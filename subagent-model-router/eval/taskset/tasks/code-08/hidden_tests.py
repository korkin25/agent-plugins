#!/usr/bin/env python3
"""Hidden tests for code-08; the subagent never sees this file.

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
MODULE = "miniini"

LINES = [
    "[main]", "[Main]", "[ spaced name ]", "[db]", "[]", "[  ]", "[open", "[x] ", "[x]junk",
    "key = value", "KEY=other", "url = http://h/?a=b&c=d", "empty =", "= nothing", "  = still nothing",
    "path=C:\\dir", "Ключ = значение", "name = a ; not a comment", "flag", "  continued text",
    "\tmore", "", "   ", "; comment", "# comment", "  ; indented", "a.b-c_d = 1",
]


def run(module):
    fixed = [
        ("empty", ""),
        ("only-comments", "; one\n# two\n\n"),
        ("crlf", "[s]\r\nk = v\r\nm = n\r\n"),
        ("lone-cr-kept", "[s]\nk = a\rb\n"),
        ("value-with-equals", "[s]\nexpr = a=b=c\n"),
        ("empty-value", "[s]\nk =\n"),
        ("key-case", "[s]\nUser = x\nUSER = y\n"),
        ("unicode-key-case", "[s]\nÄrger = 1\nКЛЮЧ = 2\n"),
        ("repeated-section-merges", "[a]\nx = 1\n[b]\ny = 2\n[a]\nz = 3\nw = 4\n"),
        ("section-case-sensitive", "[A]\nk = 1\n[a]\nk = 2\n"),
        ("empty-section", "[a]\n[b]\nk = v\n"),
        ("section-name-stripped", "[  pad  ]  \nk = v\n"),
        ("continuation-multi", "[s]\nk = one\n  two\n\tthree\nnext = 1\n"),
        ("continuation-after-blank", "[s]\nk = one\n\n  two\n"),
        ("continuation-after-comment", "[s]\nk = one\n; c\n  two\n"),
        ("continuation-after-header", "[s]\n  two\n"),
        ("continuation-first-line", "  [s]\n"),
        ("continuation-replaced-key", "[s]\nk = old\nk = new\n  more\n"),
        ("continuation-empty-start", "[s]\nk =\n  body\n"),
        ("indented-comment-is-continuation", "[s]\nk = v\n  ; part of value\n"),
        ("key-before-section", "k = v\n[s]\n"),
        ("empty-key", "[s]\n = v\n"),
        ("no-equals", "[s]\njust words\n"),
        ("empty-header", "[]\n"),
        ("blank-header", "[   ]\n"),
        ("unclosed-header", "[s\nk = v\n"),
        ("junk-after-header", "[s] x\n"),
        ("nested-brackets", "[a[b]]\nk = v\n"),
        ("line-separator-in-value", "[s]\nk = a\u2028b\x0cc\x85d\n"),
        ("no-final-newline", "[s]\nk = v"),
        ("whitespace-only-lines", "[s]\n \t \nk = v\n\u00a0\n"),
        ("nbsp-continuation", "[s]\nk = v\n\u00a0tail\n"),
        ("comment-after-key-line", "[s]\nk = v ; trailing\n# full\n"),
    ]
    for name, text in fixed:
        yield name, attempt(module.parse_ini, text)
    rng = random.Random(20261008)
    for index in range(200):
        lines = []
        if rng.random() < 0.85:
            lines.append(rng.choice(["[main]", "[db]", "[ spaced name ]"]))
        for _ in range(rng.randint(0, 12)):
            lines.append(rng.choice(LINES))
        ending = rng.choice(["\n", "\n", "\r\n"])
        text = ending.join(lines) + (ending if rng.random() < 0.7 else "")
        yield f"random-{index}", attempt(module.parse_ini, text)


if __name__ == "__main__":
    sys.exit(main())
