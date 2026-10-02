TASK: Fix the bug behind this report against the text wrapper in {workdir}.

> Bug report. `python3 wrap.py notes.txt --width 40 --bullets` prints lines longer than 40 characters,
> for example this one, which is 42 characters long:
>
>       the two new colleagues after their first
>
> Without `--bullets`, every line of the same file is at most 40 characters long, as it should be.

The module docstring of wrap.py and the docstrings of its functions state the contract. Fix the cause, not
only this file and width; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/wrap.py (the tool and its contract), {workdir}/test_wrap.py (the existing tests),
{workdir}/notes.txt (the file from the report).
EDIT: {workdir}/wrap.py only. Keep its function names and signatures and the command line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again and measure
the line lengths.
MUST_NOT: change test_wrap.py or notes.txt; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed {workdir}/wrap.py in place, and two or three sentences in your reply on the cause and the
fix.
