TASK: Fix the bug behind this report against the score statistics in {workdir}.

> Bug report. `python3 stats.py results.txt` crashes:
>
>     Traceback (most recent call last):
>       File "stats.py", line 54, in <module>
>         sys.exit(main(sys.argv[1:]))
>                  ^^^^^^^^^^^^^^^^^^
>       File "stats.py", line 41, in main
>         result = summarize(read_scores(argv[0]))
>                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
>       File "stats.py", line 32, in summarize
>         median = (ordered[middle - 1] + ordered[middle]) / 2
>                   ~~~~~~~^^^^^^^^^^^^
>     IndexError: list index out of range
>
> results.txt has fourteen scores; I expected the count, mean, median, min and max of them. The unit tests
> pass.

The module docstrings of stats.py and scores.py and the docstrings of their functions state the contract. Fix
the cause, not only this command; the rest of the documented behaviour must stay as it is.

WORKDIR: {workdir}
READ: {workdir}/stats.py (the tool and its contract), {workdir}/scores.py (the score-file reader),
{workdir}/test_stats.py (the existing tests), {workdir}/results.txt (the file from the report).
EDIT: {workdir}/stats.py and {workdir}/scores.py. Keep their function names and signatures and the command
line.
CHECKS: `python3 -m unittest` in {workdir} must still pass; run the command from the report again.
MUST_NOT: change test_stats.py or results.txt; use packages outside the Python 3.11 standard library.
OUTPUT: the fixed files in place in {workdir}, and two or three sentences in your reply on the cause and the
fix.
