#!/usr/bin/env python3
"""Hidden tests for code-07; the subagent never sees this file.

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
MODULE = "durations"

UNIT_LETTERS = "wdhms"
SPACES = ["", "", " ", "  ", "\t", "\n", " ", "　"]


def run(module):
    valid = [
        "0s", "1s", "59s", "60s", "1m", "1h30m", "1h 30m", "1h\t30m\n", "  1w  ", "1w1d1h1m1s",
        "1w 1d 1h 1m 1s", "0w0d0h0m0s", "007s", "100h", "2d4h", "999999999999999999999w", "3w 12s",
        " 1h ", "1d 5h",
    ]
    invalid = [
        "", "   ", "5", "h", "5 m", "1h30", "1H", "1M", "1x", "1y", "1h1h", "30m1h", "1s1m", "1m 1h",
        "-1h", "+1h", "1.5h", "1,5h", "1h-30m", "1h,30m", "1h_30m", "h1", "1hm", "1hh",
        "١٢s", "１h", "1h ٢m", "1 h", "1 h 30 m", "1w1d1h1m1s1s", "ms", "10mins", "1_0h", "1_000s",
    ]
    for text in valid + invalid:
        yield f"parse-{text!r}", attempt(module.parse_duration, text)
    for value in [0, 1, 59, 60, 61, 3599, 3600, 3661, 86399, 86400, 604799, 604800, 694861, 10**20, -1, -604800]:
        yield f"format-{value}", attempt(module.format_duration, value)
    rng = random.Random(20261007)
    for index in range(150):
        units = [unit for unit in UNIT_LETTERS if rng.random() < 0.5] or [rng.choice(UNIT_LETTERS)]
        pieces = [rng.choice(SPACES)]
        for unit in units:
            number = str(rng.choice([0, rng.randint(0, 99), rng.randint(0, 10**12)]))
            if rng.random() < 0.15:
                number = "0" + number
            pieces.append(number + unit + rng.choice(SPACES))
        text = "".join(pieces)
        if index % 2:
            mutation = rng.randrange(5)
            if mutation == 0:
                position = rng.randrange(len(text) + 1)
                text = text[:position] + rng.choice("wdhms 0x-.٣H") + text[position:]
            elif mutation == 1 and len(units) > 1:
                pieces[1], pieces[2] = pieces[2], pieces[1]
                text = "".join(pieces)
            elif mutation == 2:
                text = text + str(rng.randint(1, 9)) + rng.choice(units)
            elif mutation == 3 and text.strip():
                position = rng.randrange(len(text))
                text = text[:position] + text[position + 1:]
            else:
                text = text.replace(units[0], units[0].upper(), 1)
        yield f"parse-random-{index}", attempt(module.parse_duration, text)
    for index in range(80):
        value = rng.choice([rng.randint(0, 200), rng.randint(0, 10**7), rng.randint(0, 10**25),
                            rng.choice([60, 3600, 86400, 604800]) * rng.randint(1, 20)])
        formatted = attempt(module.format_duration, value)
        yield f"format-random-{index}", formatted
        if index % 4 == 0:
            text = formatted.get("value")
            yield f"roundtrip-{index}", attempt(module.parse_duration, text) if isinstance(text, str) else formatted


if __name__ == "__main__":
    sys.exit(main())
