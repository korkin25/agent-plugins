---
description: Show the agenda across all configured calendars (today, or --week)
---

Run the bundled agenda command and show its output verbatim:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/calendar-agenda" $ARGUMENTS
```

Pass `--week` through when the user asked for the week. Do not reformat or summarise the
result — it is already laid out for reading. If the command reports that it is not configured,
hand over to the `calendar-setup` skill instead of improvising.
