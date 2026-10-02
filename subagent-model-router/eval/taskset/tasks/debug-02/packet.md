TASK: Fix the bug behind this report against the expense tool in {workdir}.

> Bug report. `python3 expenses.py march.csv` stops with
>
>     error: line 4: bad amount ''
>
> and exit status 1. Line 4 is a row whose amount has not been entered yet. Such rows should simply count as
> zero; for this file the tool should print `total 187.40`.

The module docstring of expenses.py states the tool's contract. Fix the cause, not only this one file; the
rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/expenses.py (the tool and its contract), {workdir}/test_expenses.py (the existing tests),
{workdir}/march.csv (the file from the report).
EDIT: {workdir}/expenses.py only. Keep its function and class names, their signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again.
MUST_NOT: change test_expenses.py or march.csv; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/expenses.py in place, and two or three sentences in your reply on the cause and
the fix.
