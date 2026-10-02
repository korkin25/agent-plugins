TASK: Convert the inventory table in the Markdown file into a CSV file.
WORKDIR: {workdir}
READ: {workdir}/inventory.md
EDIT: create {workdir}/inventory.csv; do not modify inventory.md.
CHECKS: none are provided; the rules below are checked by parsing the file as CSV.
OUTPUT: inventory.csv, UTF-8 text:
- one CSV record per table row, starting with the header row; the Markdown alignment row (the one made of dashes and colons) is not a data row and is left out;
- fields separated by commas, in the table's column order;
- each field is the cell text with the surrounding spaces removed and nothing else changed; an empty cell becomes an empty field;
- quoting as in RFC 4180: a field that contains a comma or a double quote is enclosed in double quotes, and every double quote inside such a field is written twice. Quoting other fields as well is allowed;
- line endings may be LF or CRLF; a final line break is optional.
