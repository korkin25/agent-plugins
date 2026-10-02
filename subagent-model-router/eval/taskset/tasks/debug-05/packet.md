TASK: Fix the bug behind this report against the price-list tool in {workdir}.

> Bug report. `python3 pricebook.py prices.txt 4000 6000` never finishes; after a minute of 100 % CPU I had to
> press Ctrl-C. I expected the number of prices from 4000 to 6000 and then the prices themselves.
> `python3 pricebook.py prices.txt 0 6000` does answer at once.

The module docstring of pricebook.py states the tool's contract, and each function's docstring states what it
returns. Fix the cause, not only this one query; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/pricebook.py (the tool and its contract), {workdir}/test_pricebook.py (the existing tests),
{workdir}/prices.txt (the file from the report).
EDIT: {workdir}/pricebook.py only. Keep its function names and signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again (with a
timeout, in case it still hangs).
MUST_NOT: change test_pricebook.py or prices.txt; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/pricebook.py in place, and two or three sentences in your reply on the cause and
the fix.
