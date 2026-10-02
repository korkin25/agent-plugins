#!/usr/bin/env python3
"""Hidden tests for code-02; the subagent never sees this file.

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
MODULE = "luhn"


def shifted(digits, zero):
    """The same number with its ASCII digits written from another Unicode zero (fullwidth, Arabic-Indic ...)."""
    return "".join(chr(ord(zero) + int(char)) if char in "0123456789" else char for char in digits)


def run(module):
    numbers = [
        "79927398713", "79927398710", "7992 7398 713", " 79927398713 ", "4539 1488 0343 6467", "4539148803436468",
        "0", "00", "000", "18", "26", "59", "91", "34", "", " ", "  0  0 ", "1 8", "8", "5",
        "4111-1111-1111-1111", "4111111111111111", "4111111111111112", "12a4", "+18", "0x18", "1-8", "18.",
        "99999999999999999999999999999999999999999999999994",
        "2222 4000 7000 0005", "378282246310005", "6011111111111117", "5105105105105100", "5105105105105106",
        shifted("79927398713", "\uff10"), shifted("7992 7398 713", "\u0660"), shifted("18", "\u0966"),
        "1" + shifted("8", "\uff10"), shifted("00", "\u06f0"), "1\u2078", "\u00b9\u2078",
    ]
    for index, number in enumerate(numbers):
        yield f"is_valid-{index}", attempt(module.is_valid, number)
    payloads = [
        "7992739871", "0", "1", "9", "00", "12345", "123456", "411111111111111", "37828224631000",
        "999999999999999999999999999999", "", " ", "12 34", "12a", "-5", "1.5",
        shifted("7992739871", "\u0660"), shifted("123", "\uff10"), "12" + shifted("3", "\u0966"), "\u00b2",
    ]
    for index, payload in enumerate(payloads):
        yield f"check_digit-{index}", attempt(module.check_digit, payload)
    rng = random.Random(20261002)
    for index in range(60):
        digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 25)))
        yield f"random-valid-{index}", attempt(module.is_valid, digits)
        yield f"random-digit-{index}", attempt(module.check_digit, digits)


if __name__ == "__main__":
    sys.exit(main())
