TASK: A sequence of integers is defined by

    x_0 = 2026
    x_(n+1) = (x_n * x_n + 11) mod 1000003   for every n >= 0,

where "a mod m" is the remainder of a divided by m, an integer from 0 to m - 1. Find x_N for N = 10^18, that is, the
term with index 1,000,000,000,000,000,000 (x_0 is the term with index 0).
WORKDIR: {workdir}
READ: nothing; the task is self-contained.
EDIT: create {workdir}/answer.txt; change nothing else.
CHECKS: none are provided; make sure of the answer before you write it.
OUTPUT: answer.txt holds x_N as a decimal integer: digits only, nothing else in the file.
