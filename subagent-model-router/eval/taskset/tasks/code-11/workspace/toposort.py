"""Ordering tasks that depend on each other."""


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
    raise NotImplementedError
