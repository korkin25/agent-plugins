"""Ordering tasks that depend on each other."""

from collections import deque


class CycleError(ValueError):
    """Raised by ``topo_order`` when no order exists; ``cycle`` holds one dependency cycle."""

    def __init__(self, cycle):
        super().__init__(f"dependency cycle: {' -> '.join(map(str, cycle))}")
        self.cycle = cycle


def topo_order(nodes, edges):
    """Return the nodes in an order that respects every edge, or raise ``CycleError``.

    ``nodes`` is a list of node names (strings). ``edges`` is a list of pairs ``(a, b)`` meaning "``a`` must come
    before ``b``". The same edge may be listed more than once; it means the same as listing it once. Graphs may
    have up to 10 000 nodes and 50 000 edges.

    Errors are checked in this order:

    * a name that appears more than once in ``nodes``, or an edge that mentions a name not in ``nodes``, raises
      ``ValueError`` (not ``CycleError``);
    * if no order respects all edges, raise ``CycleError(cycle)`` where ``cycle`` is a list
      ``[v0, v1, ..., vk, v0]``: ``v0`` ... ``vk`` are distinct nodes, ``k >= 0``, and every consecutive pair
      ``(cycle[i], cycle[i + 1])`` is an edge. Any cycle of the graph is acceptable. A self-loop ``(a, a)`` is
      the cycle ``[a, a]``.

    Otherwise return a list containing every node exactly once in which ``a`` stands before ``b`` for every edge
    ``(a, b)``. Of all such lists, return the lexicographically smallest one, comparing node names with the
    ordinary ``str`` ordering: at every position the smallest name that may come next is chosen. An empty
    ``nodes`` list gives ``[]``.
    """
    nodes = list(nodes)
    known = set(nodes)
    if len(known) != len(nodes):
        raise ValueError("a node is listed more than once")
    successors = {node: set() for node in nodes}
    for a, b in edges:
        if a not in known or b not in known:
            raise ValueError(f"edge ({a!r}, {b!r}) mentions an unknown node")
        successors[a].add(b)
    indegree = {node: 0 for node in nodes}
    for node in nodes:
        for target in successors[node]:
            indegree[target] += 1
    ready = deque(node for node in nodes if indegree[node] == 0)
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for target in successors[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(order) == len(nodes):
        return order
    raise CycleError(_find_cycle(successors, {node for node in nodes if indegree[node] > 0}))


def _find_cycle(successors, remaining):
    """Every remaining node has a remaining predecessor, so walking backwards must revisit a node."""
    predecessors = {node: [] for node in remaining}
    for source in remaining:
        for target in successors[source]:
            if target in remaining:
                predecessors[target].append(source)
    position = {}
    path = []
    current = min(remaining)
    while current not in position:
        position[current] = len(path)
        path.append(current)
        current = min(predecessors[current])
    loop = path[position[current]:]
    loop.reverse()
    return loop + [loop[0]]
