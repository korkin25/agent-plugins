TASK: Edit the release notes so that they follow the documentation style guide.
WORKDIR: {workdir}
READ: {workdir}/release_notes.md (the draft) and {workdir}/style_guide.md (the rules).
EDIT: create {workdir}/release_notes_edited.md; do not modify the two input files.
CHECKS: none are provided. The check compares release_notes_edited.md with the expected text character by character after every run of spaces and line breaks has been replaced by a single space and leading and trailing whitespace has been dropped. Line wrapping is therefore free; every other character counts.
OUTPUT: release_notes_edited.md: the complete release notes with every style-guide rule applied and nothing else changed. Keep the Markdown markup (heading markers, list dashes, quotation marks) as it is in the draft.
