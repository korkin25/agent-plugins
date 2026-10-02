TASK: Fix the bug behind this report against the sales summary in {workdir}.

> Bug report. `python3 sales_report.py sales.csv` should print one line for each of our five regions and then
> the total, but the September file gives 32 lines, and the same region shows up again and again. The
> output starts like this:
>
>     Central  1  98.00  0.6%
>     Central  1  210.69  1.2%
>     Central  1  274.75  1.6%
>     Central  1  504.30  2.9%
>     Central  1  622.80  3.5%
>     Central  1  823.25  4.7%
>
> I expected each region once, with the count and total of all its sales.

The module docstring of sales_report.py and the docstrings of its functions state the contract. Fix the cause,
not only this file; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/sales_report.py (the tool and its contract), {workdir}/test_sales_report.py (the existing
tests), {workdir}/sales.csv (the file from the report).
EDIT: {workdir}/sales_report.py only. Keep its function names and signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again.
MUST_NOT: change test_sales_report.py or sales.csv; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/sales_report.py in place, and two or three sentences in your reply on the cause and
the fix.
