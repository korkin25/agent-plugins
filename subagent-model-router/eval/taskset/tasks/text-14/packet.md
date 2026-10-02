TASK: Turn the mixed-style reference list into a clean, deduplicated, sorted reference list that follows the report's reference style.
WORKDIR: {workdir}
READ: {workdir}/refs.txt (the collected references) and {workdir}/style.md (the reference style, eight rules).
EDIT: create {workdir}/references.txt; do not modify the input files.
CHECKS: none are provided. The check compares references.txt line by line with the expected list; trailing spaces, blank lines and the line-ending style (LF or CRLF) are ignored, every other character counts.
OUTPUT: references.txt, UTF-8 text: one reference per line in the pattern from style.md, numbered from [1], and nothing else in the file.
