TASK: Fix the bug behind this report against the due-date tool in {workdir}.

> Bug report. `python3 workdays.py 2026-10-01 3` prints `2026-10-05`. 1 October 2026 is a Thursday, so the
> three business days after it are Friday, Monday and Tuesday: the answer should be `2026-10-06`. Our
> due dates come out too early whenever a weekend is in the way; I have not checked holidays yet.

The module docstring of workdays.py and the docstrings of its functions state the contract. Fix the cause,
not only this date; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/workdays.py (the tool and its contract), {workdir}/test_workdays.py (the existing tests),
{workdir}/holidays.txt (the office's holiday file).
EDIT: {workdir}/workdays.py only. Keep its function names and signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again, also with
`--holidays holidays.txt`.
MUST_NOT: change test_workdays.py or holidays.txt; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/workdays.py in place, and two or three sentences in your reply on the cause and
the fix.
