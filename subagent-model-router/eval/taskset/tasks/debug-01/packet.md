TASK: Fix the bug behind this report against the Roman-numeral tool in {workdir}.

> Bug report. `python3 roman.py 1944` prints `MCMXXXXIV`. The year should come out as `MCMXLIV`.

The module docstring of roman.py says what the tool must produce. Fix the cause, not only the number in the
report; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/roman.py (the tool and its contract), {workdir}/test_roman.py (the existing tests).
EDIT: {workdir}/roman.py only. Keep its function names and signatures and its command line as they are.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again.
MUST_NOT: change test_roman.py; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/roman.py in place, and two or three sentences in your reply on the cause and the fix.
