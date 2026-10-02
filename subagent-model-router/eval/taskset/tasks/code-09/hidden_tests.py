#!/usr/bin/env python3
"""Hidden tests for code-09; the subagent never sees this file.

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
MODULE = "ttlcache"
MISSING = "<missing>"


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def scenario(module, capacity, ttl, ops):
    """Run ops against a fresh cache; record every observable answer, stop at the first unexpected exception."""
    clock = FakeClock()
    created = attempt(module.TTLCache, capacity, ttl, clock=clock)
    if "value" not in created:
        return created
    cache = module.TTLCache(capacity, ttl, clock=clock)
    log = []
    for op in ops:
        kind = op[0]
        try:
            if kind == "tick":
                clock.now += op[1]
                continue
            if kind == "put":
                cache.put(op[1], op[2])
                continue
            if kind == "get":
                log.append(["get", op[1], canon(cache.get(op[1], MISSING))])
            elif kind == "in":
                log.append(["in", op[1], canon(op[1] in cache)])
            elif kind == "len":
                log.append(["len", canon(len(cache))])
            else:
                log.append(["keys", canon(list(cache.keys()))])
        except Exception as exc:  # noqa: BLE001
            log.append(["error", kind, type(exc).__name__])
            break
    return {"value": log}


def random_ops(rng, keys, steps, ticks):
    ops = []
    for _ in range(steps):
        roll = rng.random()
        key = rng.choice(keys)
        if roll < 0.30:
            ops.append(("put", key, rng.randint(0, 99)))
        elif roll < 0.50:
            ops.append(("get", key))
        elif roll < 0.60:
            ops.append(("in", key))
        elif roll < 0.68:
            ops.append(("len",))
        elif roll < 0.78:
            ops.append(("keys",))
        else:
            ops.append(("tick", rng.choice(ticks)))
    ops.append(("keys",))
    ops.append(("len",))
    return ops


def run(module):
    for capacity, ttl in [(0, 1), (-1, 1), (1, 0), (1, -2.5), (2, 0.0), (2.0, 1), (2.5, 1), ("3", 1), (None, 1),
                          (2, "1"), (2, None)]:
        yield f"constructor-{capacity!r}-{ttl!r}", attempt(module.TTLCache, capacity, ttl)
    fixed = {
        "expires-at-exact-boundary": (3, 4, [("put", "a", 1), ("tick", 3.75), ("in", "a"), ("tick", 0.25),
                                             ("in", "a"), ("get", "a"), ("len",), ("keys",)]),
        "get-does-not-extend": (3, 4, [("put", "a", 1), ("tick", 3), ("get", "a"), ("tick", 1), ("get", "a")]),
        "put-renews": (3, 4, [("put", "a", 1), ("tick", 3), ("put", "a", 2), ("tick", 3), ("get", "a"),
                              ("tick", 1), ("in", "a")]),
        "contains-is-not-a-use": (2, 100, [("put", "a", 1), ("put", "b", 2), ("in", "a"), ("put", "c", 3),
                                           ("keys",)]),
        "get-is-a-use": (2, 100, [("put", "a", 1), ("put", "b", 2), ("get", "a"), ("put", "c", 3), ("keys",)]),
        "failed-get-is-not-a-use": (2, 100, [("put", "a", 1), ("put", "b", 2), ("get", "zz"), ("put", "c", 3),
                                             ("keys",)]),
        "expired-not-counted-for-capacity": (2, 10, [("put", "a", 1), ("tick", 1), ("put", "b", 2), ("get", "a"),
                                                     ("tick", 9.5), ("put", "c", 3), ("keys",), ("get", "b"),
                                                     ("len",)]),
        "len-ignores-expired": (5, 2, [("put", "a", 1), ("put", "b", 2), ("tick", 1), ("put", "c", 3),
                                       ("len",), ("tick", 1), ("len",), ("keys",), ("tick", 1), ("len",)]),
        "replace-moves-to-end": (3, 100, [("put", "a", 1), ("put", "b", 2), ("put", "a", 3), ("keys",),
                                          ("put", "c", 4), ("put", "d", 5), ("keys",), ("get", "a")]),
        "capacity-one": (1, 100, [("put", "a", 1), ("put", "b", 2), ("get", "a"), ("get", "b"), ("len",)]),
        "none-value-stored": (2, 100, [("put", "a", None), ("get", "a"), ("in", "a"), ("len",)]),
        "reinsert-after-expiry": (2, 1, [("put", "a", 1), ("put", "b", 2), ("tick", 1), ("put", "a", 3),
                                         ("keys",), ("get", "b"), ("len",)]),
        "fractional-ttl": (4, 0.75, [("put", 1, "x"), ("tick", 0.5), ("put", 2, "y"), ("tick", 0.25),
                                     ("keys",), ("tick", 0.5), ("keys",), ("len",)]),
    }
    for name, (capacity, ttl, ops) in fixed.items():
        yield name, scenario(module, capacity, ttl, ops)
    real = attempt(lambda: (lambda c: (c.put("k", "v"), c.get("k"), len(c))[1:])(module.TTLCache(2, 3600)))
    yield "default-clock", real
    rng = random.Random(20261009)
    for index in range(150):
        capacity = rng.randint(1, 5)
        ttl = rng.choice([1, 2, 2.5, 4, 10])
        keys = ["a", "b", "c", "d", "e", "f", 7][: rng.randint(2, 7)]
        ops = random_ops(rng, keys, rng.randint(5, 60), [0.25, 0.5, 1, 1, 2, 3.5])
        yield f"random-{index}", scenario(module, capacity, ttl, ops)


if __name__ == "__main__":
    sys.exit(main())
