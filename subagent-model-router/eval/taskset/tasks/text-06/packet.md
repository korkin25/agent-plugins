TASK: Write a short summary of a resolved incident for the company-wide status digest.
WORKDIR: {workdir}
READ: {workdir}/incident.md
EDIT: create {workdir}/summary.txt; change nothing else.
CHECKS: none are provided; the constraints below are checked automatically.
OUTPUT: summary.txt holds the summary as plain text in English.
- Length: at most 60 words. A word is any whitespace-separated token, so "lb-east-2," or "47" each count as one word.
- It must include all of the following, as stated in the report:
  - the date of the incident, written as YYYY-MM-DD;
  - the outage duration in minutes, written with digits;
  - the number of failed payment requests, written with digits (a thousands separator is allowed);
  - the surname of the engineer who restored the service;
  - the root cause, using the exact phrase "expired TLS certificate".
- It must not include:
  - the names of affected merchants;
  - the internal ticket number;
  - any clock time (such as 10:15 or 10:15 UTC).
