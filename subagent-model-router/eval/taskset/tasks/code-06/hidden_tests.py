#!/usr/bin/env python3
"""Hidden tests for code-06; the subagent never sees this file.

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
MODULE = "roman"


def run(module):
    for n in [0, -1, -3999, 4000, 4001, 10000]:
        yield f"to-out-of-range-{n}", attempt(module.to_roman, n)
    for n in [1, 4, 9, 14, 40, 90, 400, 900, 1994, 2024, 3888, 3999]:
        yield f"to-{n}", attempt(module.to_roman, n)
    roundtrip = []
    for n in range(1, 4000):
        try:
            text = module.to_roman(n)
            roundtrip.append([text, module.from_roman(text)])
        except Exception as exc:  # recorded, compared with the reference
            roundtrip.append(["error", type(exc).__name__])
            break
    yield "roundtrip-all", {"value": canon(roundtrip)}
    invalid = [
        "", "IIII", "VV", "IC", "XM", "IL", "VX", "LC", "DM", "XXXX", "CCCC", "MMMM", "MMMMCMXCIX",
        "IIV", "IXI", "XCX", "CMC", "IVI", "DD", "LL", "iv", "xlii", "Mcm", " XIV", "XIV ", "XIV\n",
        "X I V", "ⅩⅣ", "IIX", "VIV", "CDD", "MCMC", "0", "12", "-X", "XIIII",
    ]
    for text in invalid:
        yield f"from-invalid-{text!r}", attempt(module.from_roman, text)
    rng = random.Random(20261006)
    for index in range(150):
        text = "".join(rng.choice("IVXLCDM") for _ in range(rng.randint(1, 7)))
        yield f"from-random-{index}", attempt(module.from_roman, text)


if __name__ == "__main__":
    sys.exit(main())
