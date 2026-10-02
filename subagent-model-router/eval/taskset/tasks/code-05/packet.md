TASK: Implement `first_error` in {workdir}/brackets.py so that it meets the specification in the module and function docstrings.
WORKDIR: {workdir}
READ: {workdir}/brackets.py (the docstrings are the specification); {workdir}/tests/test_visible.py.
EDIT: {workdir}/brackets.py. You may add test files under {workdir}/tests/; change nothing else.
CHECKS: `cd {workdir} && python3 -m unittest discover -s tests -v` must pass. The visible tests are a small sample, not the acceptance suite: the module is accepted against the whole docstring specification.
OUTPUT: {workdir}/brackets.py with `first_error` implemented: Python 3.11, standard library only, the function name and signature unchanged, nothing printed and no files read or written.
MUST_NOT: rename the function or change its signature; add third-party dependencies.
