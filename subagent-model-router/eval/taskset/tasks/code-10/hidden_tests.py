#!/usr/bin/env python3
"""Hidden tests for code-10; the subagent never sees this file.

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
MODULE = "autocomplete"

WORDS = ["кот", "кошка", "кол", "колесо", "ко", "к", "Кот", "ёж", "ёлка", "яма", "ящик", "жук", "жёлудь",
         "желе", "cat", "car", "Cat", "ёё", "еж", "кот ", "мир", "Мир", "миръ"]


def scenario(module, ops):
    created = attempt(module.Autocomplete)
    if "value" not in created:
        return created
    ac = module.Autocomplete()
    log = []
    for op in ops:
        kind, args = op[0], op[1:]
        method = {"add": ac.add, "remove": ac.remove, "score": ac.score, "complete": ac.complete,
                  "len": ac.__len__}[kind]
        outcome = attempt(method, *args)
        if "error" in outcome:
            log.append([kind, outcome])
            break
        if kind != "add" or "raises" in outcome:
            log.append([kind, list(args), outcome])
    return {"value": log}


def run(module):
    fixed = {
        "yo-after-ya": [("add", "яма"), ("add", "ёж"), ("add", "еж"), ("add", "жук"), ("complete", "", 10)],
        "capitals-first": [("add", "мир"), ("add", "Мир"), ("add", "Миръ"), ("complete", "", 5),
                           ("complete", "М", 5)],
        "prefix-is-word": [("add", "ко", 2), ("add", "кот", 2), ("add", "кол", 5), ("complete", "ко", 10),
                           ("complete", "кот", 10), ("complete", "котик", 10)],
        "ties-alphabetical": [("add", "ящик", 2), ("add", "жук", 2), ("add", "кол", 2), ("add", "ёлка", 2),
                              ("complete", "", 3), ("complete", "", 4)],
        "accumulate": [("add", "кот"), ("add", "кот", 4), ("add", "кол", 3), ("score", "кот"),
                       ("complete", "ко", 1), ("len",)],
        "remove-keeps-longer-words": [("add", "к"), ("add", "ко"), ("add", "кот"), ("add", "кошка"),
                                      ("remove", "ко"), ("complete", "к", 10), ("len",), ("score", "кот")],
        "remove-missing": [("add", "кот"), ("remove", "ко"), ("remove", "котик"), ("remove", "мир"),
                           ("len",)],
        "readd-after-remove": [("add", "кот", 7), ("remove", "кот"), ("add", "кот"), ("score", "кот"),
                               ("len",)],
        "k-limits": [("add", "a"), ("add", "b"), ("complete", "", 0), ("complete", "", -3), ("complete", "", 1),
                     ("complete", "", 100)],
        "validation": [("add", ""), ("add", "кот", 0), ("add", "кот", -2), ("add", "кот", 1.5), ("len",),
                       ("score", "кот"), ("complete", "", 5)],
        "trailing-space-distinct": [("add", "кот"), ("add", "кот ", 2), ("complete", "кот", 5)],
        "empty-dictionary": [("complete", "", 5), ("complete", "к", 5), ("len",), ("score", "к")],
        "score-of-prefix": [("add", "колесо", 4), ("score", "кол"), ("score", "колесо"), ("score", "")],
    }
    for name, ops in fixed.items():
        yield name, scenario(module, ops)
    rng = random.Random(20261010)
    for index in range(150):
        ops = []
        words = rng.sample(WORDS, rng.randint(2, len(WORDS)))
        for _ in range(rng.randint(3, 40)):
            roll = rng.random()
            word = rng.choice(words)
            if roll < 0.45:
                ops.append(("add", word, rng.choice([1, 1, 2, 3, 5])))
            elif roll < 0.55:
                ops.append(("remove", word))
            elif roll < 0.62:
                ops.append(("score", word))
            elif roll < 0.95:
                ops.append(("complete", word[: rng.randint(0, len(word))], rng.randint(-1, 8)))
            else:
                ops.append(("len",))
        ops.append(("complete", "", 50))
        yield f"random-{index}", scenario(module, ops)


if __name__ == "__main__":
    sys.exit(main())
