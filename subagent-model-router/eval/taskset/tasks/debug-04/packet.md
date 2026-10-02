TASK: Fix the bug behind this report against the pager in {workdir}.

> Bug report. plants.txt lists 25 plants, but `python3 pager.py plants.txt --per-page 10` prints only
> `page 1/2` and `page 2/2` and stops after Tulip, the 20th. Verbena, Zinnia and the others never show up.
> There should be three pages, the third with the last five plants.

The module docstring of pager.py states the tool's contract. Fix the cause, not only this file and page
size; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/pager.py (the tool and its contract), {workdir}/test_pager.py (the existing tests),
{workdir}/plants.txt (the file from the report).
EDIT: {workdir}/pager.py only. Keep its function names and signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again.
MUST_NOT: change test_pager.py or plants.txt; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/pager.py in place, and two or three sentences in your reply on the cause and the
fix.
