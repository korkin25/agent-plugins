TASK: How many integers n with 1 <= n <= 1,000,000 satisfy all three of the following conditions?

1. n leaves remainder 3 when divided by 7.
2. n leaves remainder 5 when divided by 11.
3. gcd(n, 30) = 1, that is, n and 30 have no common divisor greater than 1.
WORKDIR: {workdir}
READ: nothing; the task is self-contained.
EDIT: create {workdir}/answer.txt; change nothing else.
CHECKS: none are provided; make sure of the answer before you write it.
OUTPUT: answer.txt holds the count as a decimal integer: digits only, no sign, no thousands separators, nothing else in the file.
