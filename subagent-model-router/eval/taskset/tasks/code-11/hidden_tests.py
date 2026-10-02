#!/usr/bin/env python3
"""Hidden tests for code-11; the subagent never sees this file.

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
MODULE = "toposort"

NAMES = ["a", "b", "c", "aa", "ab", "B", "Z", "b10", "b9", "ä", "Ω", "z", "_", "1", "10", "2", "ё", "е"]


def cycle_problem(cycle, edges, nodes):
    """None if cycle is a valid cycle of the graph, otherwise a short reason."""
    if not isinstance(cycle, (list, tuple)) or len(cycle) < 2:
        return "cycle is not a list of at least two names"
    cycle = list(cycle)
    if cycle[0] != cycle[-1]:
        return "cycle does not return to its first node"
    body = cycle[:-1]
    if len(set(body)) != len(body):
        return "cycle repeats a node"
    edge_set = {tuple(edge) for edge in edges}
    for a, b in zip(cycle, cycle[1:]):
        if (a, b) not in edge_set:
            return f"({a!r}, {b!r}) is not an edge"
    return None


def topo_case(module, nodes, edges):
    try:
        order = module.topo_order(list(nodes), [tuple(edge) for edge in edges])
    except module.CycleError as exc:
        problem = cycle_problem(getattr(exc, "cycle", None), edges, nodes)
        return {"cycle": "valid" if problem is None else f"invalid: {problem}"}
    except ValueError:
        return {"raises": "ValueError"}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}
    return {"value": canon(order)}


def random_graph(rng, size, edge_count, acyclic):
    nodes = rng.sample(NAMES, size)
    rank = nodes[:]
    rng.shuffle(rank)
    edges = []
    for _ in range(edge_count):
        i, j = rng.randrange(size), rng.randrange(size)
        if acyclic:
            if i == j:
                continue
            i, j = min(i, j), max(i, j)
        edges.append((rank[i], rank[j]))
    if edges and rng.random() < 0.3:
        edges += rng.sample(edges, min(len(edges), 3))
    return nodes, edges


def run(module):
    fixed = {
        "empty": ([], []),
        "single": (["only"], []),
        "no-edges-sorted": (["b", "c", "a", "B"], []),
        "string-order": (["b9", "b10", "a", "Z"], [("a", "b10")]),
        "smallest-not-bfs": (["a", "b", "c", "d"], [("d", "a"), ("b", "c")]),
        "unlock-smaller-later": (["x", "c", "a"], [("x", "a")]),
        "diamond": (["d", "c", "b", "a"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]),
        "duplicate-edges": (["a", "b", "c"], [("b", "a"), ("b", "a"), ("c", "b"), ("c", "b")]),
        "duplicate-node": (["a", "b", "a"], []),
        "duplicate-and-cycle": (["a", "b", "a"], [("a", "b"), ("b", "a")]),
        "unknown-source": (["a"], [("q", "a")]),
        "unknown-and-cycle": (["a", "b"], [("a", "b"), ("b", "a"), ("b", "c")]),
        "self-loop": (["a", "b"], [("a", "b"), ("b", "b")]),
        "two-cycle": (["a", "b", "c"], [("a", "b"), ("b", "a")]),
        "cycle-with-tail": (["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("c", "b"), ("c", "d")]),
        "cycle-feeds-node": (["a", "b", "c"], [("a", "b"), ("b", "a"), ("b", "c")]),
        "unicode-names": (["ё", "е", "Ω", "ä", "z"], [("z", "ä")]),
        "long-chain": ([f"n{i:05d}" for i in range(5000)][::-1],
                       [(f"n{i:05d}", f"n{i + 1:05d}") for i in range(4999)]),
        "long-cycle": ([f"n{i:05d}" for i in range(5000)],
                       [(f"n{i:05d}", f"n{(i + 1) % 5000:05d}") for i in range(5000)]),
        "long-chain-reverse-names": ([f"n{i:05d}" for i in range(4000)],
                                     [(f"n{i + 1:05d}", f"n{i:05d}") for i in range(3999)]),
    }
    for name, (nodes, edges) in fixed.items():
        yield name, topo_case(module, nodes, edges)
    rng = random.Random(20261011)
    for index in range(200):
        size = rng.randint(1, len(NAMES))
        nodes, edges = random_graph(rng, size, rng.randint(0, 2 * size), acyclic=index % 3 != 0)
        yield f"random-{index}", topo_case(module, nodes, edges)
    big_names = [f"t{rng.randrange(10**9):09d}" for _ in range(3000)]
    big_names = sorted(set(big_names))
    rng.shuffle(big_names)
    big_edges = []
    for _ in range(20000):
        i, j = sorted(rng.sample(range(len(big_names)), 2))
        big_edges.append((big_names[i], big_names[j]))
    yield "big-dag", topo_case(module, big_names, big_edges)
    yield "big-cyclic", topo_case(module, big_names, big_edges + [(big_names[-1], big_names[0])])


if __name__ == "__main__":
    sys.exit(main())
