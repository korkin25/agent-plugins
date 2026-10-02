TASK: A walker moves on the integer lattice from the point (0, 0) to the point (12, 9). Every step goes from (x, y)
either to (x + 1, y) or to (x, y + 1). These seven points are blocked, and a path may not pass through any of them:

    (2, 1), (3, 4), (5, 2), (6, 6), (8, 3), (9, 7), (4, 8)

Each point is written as (x, y). How many different paths lead from (0, 0) to (12, 9)?
WORKDIR: {workdir}
READ: nothing; the task is self-contained.
EDIT: create {workdir}/answer.txt; change nothing else.
CHECKS: none are provided; make sure of the answer before you write it.
OUTPUT: answer.txt holds the count as a decimal integer: digits only, no sign, no thousands separators, nothing else in the file.
