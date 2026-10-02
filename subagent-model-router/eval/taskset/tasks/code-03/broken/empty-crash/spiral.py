"""Reading a matrix in spiral order."""


def spiral_order(matrix):
    """Return the elements of ``matrix`` in clockwise spiral order.

    ``matrix`` is a list of rows; every row is a list and all rows have the same length. The walk starts at the
    top-left element, goes right along the top row, down the right column, left along the bottom row, up the left
    column, and continues inwards the same way until every element has been visited exactly once.

    ``[[1, 2, 3], [4, 5, 6], [7, 8, 9]]`` gives ``[1, 2, 3, 6, 9, 8, 7, 4, 5]``.

    A matrix with no rows (``[]``) or whose rows are all empty (``[[]]``, ``[[], []]``) gives ``[]``.
    Raises ``ValueError`` if the rows do not all have the same length. The argument is left unchanged.
    """
    width = len(matrix[0])
    if any(len(row) != width for row in matrix):
        raise ValueError("rows differ in length")
    result = []
    top, bottom, left, right = 0, len(matrix) - 1, 0, width - 1
    while top <= bottom and left <= right:
        for col in range(left, right + 1):
            result.append(matrix[top][col])
        for row in range(top + 1, bottom + 1):
            result.append(matrix[row][right])
        if top < bottom:
            for col in range(right - 1, left - 1, -1):
                result.append(matrix[bottom][col])
        if left < right:
            for row in range(bottom - 1, top, -1):
                result.append(matrix[row][left])
        top, bottom, left, right = top + 1, bottom - 1, left + 1, right - 1
    return result
