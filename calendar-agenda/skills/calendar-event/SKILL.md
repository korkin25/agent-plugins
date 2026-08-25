---
name: calendar-event
description: Schedule, move, cancel or look up events in the user's Google Calendars. Use when they ask to book or block time, set a reminder tied to a date, move or cancel a meeting, ask what is on today or this week, or ask when they are free — in any language.
---

# Calendar

The user's calendars are reachable through the **`google-calendar` MCP server** that ships with
this plugin. Which calendars exist, and which one may be written to, is read from
`~/.config/calendar-agenda/config.json` — **read that file first**; it is the only source of
truth for calendar ids. If it is missing, the plugin is not set up: point the user at the
`calendar-setup` skill instead of guessing an address.

Tools: `get-current-time`, `list-calendars`, `list-events`, `search-events`, `get-event`,
`get-freebusy`, `create-event`, `create-events`, `update-event`, `delete-event`,
`list-colors`, `respond-to-event`.

## Rules

**Resolve dates with `get-current-time`, never from memory.** "Tomorrow", "Wednesday", "next
week" must be computed from the tool's answer. A wrong date is the most common failure here,
and the user only finds out when they miss the thing.

**Never pass `primary` as `calendarId`.** Use the explicit ids from the config. Under a service
account `primary` is the service account's own empty calendar, so an event created there
silently goes nowhere; under OAuth it is merely ambiguous when several calendars are configured.

**Check availability across every configured calendar before proposing a time.** One call
covers them all:

```
get-freebusy(calendars=[{id: "<id1>"}, {id: "<id2>"}, …], timeMin=…, timeMax=…, timeZone=…)
```

A slot is free only when it is free in **all** of them. Proposing a time that collides with a
meeting on another calendar is the failure this rule exists to prevent, and the user will not
notice until it starts.

**Write only to a calendar marked `"writable": true`.** Writing elsewhere will be refused by
Google; say so and explain that access has to be granted on that calendar's side, rather than
retrying.

**Confirm before writing.** Show summary, date, weekday, time, duration and timezone, and get a
yes before `create-event` or `update-event`. For `delete-event` require an explicit confirmation
every time — it is not reversible from here.

**Timezone:** use the one from the config; when it is `null`, that means the machine's local
zone, so pass the value `get-current-time` reports. Always send `timeZone` explicitly so the
event is unambiguous if the user travels.

**Reminders:** if the config carries a `reminders` array, attach exactly that set with
`useDefault: false`. Google allows at most five overrides per event. `popup` reminders reach the
phone; `email` ones do not.

**Duplicated calendars.** Some people sync a work calendar into a personal one, so the same
meeting appears twice under a generic title such as "Meeting" or "Busy". Treat those as one
event; never create a copy of an event that already exists on another configured calendar.

**Report back concretely:** weekday, date, local time, and what was created — not "done".

## Showing the agenda

For "what's on today / this week", prefer the bundled command over assembling tool calls — it
merges every configured calendar, collapses synced duplicates and shortens meeting links:

```
${CLAUDE_PLUGIN_ROOT}/bin/calendar-agenda           # today
${CLAUDE_PLUGIN_ROOT}/bin/calendar-agenda --week    # the next seven days
${CLAUDE_PLUGIN_ROOT}/bin/calendar-agenda --json    # structured, for further reasoning
```

A `SessionStart` hook already runs it at the start of each session and puts the result in
context, so the day's agenda is usually there before the user asks. Do not fetch it again in the
same session unless they ask for a fresh look or the day has rolled over.
