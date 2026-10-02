TASK: Implement the `TTLCache` class in {workdir}/ttlcache.py so that it meets the specification in the module, class and method docstrings.
WORKDIR: {workdir}
READ: {workdir}/ttlcache.py (the docstrings are the specification); {workdir}/tests/test_visible.py.
EDIT: {workdir}/ttlcache.py. You may add test files under {workdir}/tests/; change nothing else.
CHECKS: `cd {workdir} && python3 -m unittest discover -s tests -v` must pass. The visible tests are a small sample, not the acceptance suite: the module is accepted against the whole docstring specification.
OUTPUT: {workdir}/ttlcache.py with `TTLCache` implemented: Python 3.11, standard library only, the class name, method names and signatures unchanged, nothing printed and no files read or written.
MUST_NOT: rename the class or its methods or change their signatures; add third-party dependencies.
