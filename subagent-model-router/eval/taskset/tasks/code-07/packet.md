TASK: Implement `parse_duration` and `format_duration` in {workdir}/durations.py so that it meets the specification in the module and function docstrings.
WORKDIR: {workdir}
READ: {workdir}/durations.py (the docstrings are the specification); {workdir}/tests/test_visible.py.
EDIT: {workdir}/durations.py. You may add test files under {workdir}/tests/; change nothing else.
CHECKS: `cd {workdir} && python3 -m unittest discover -s tests -v` must pass. The visible tests are a small sample, not the acceptance suite: the module is accepted against the whole docstring specification.
OUTPUT: {workdir}/durations.py with `parse_duration` and `format_duration` implemented: Python 3.11, standard library only, the function names and signatures unchanged, nothing printed and no files read or written.
MUST_NOT: rename the functions or change their signatures; add third-party dependencies.
