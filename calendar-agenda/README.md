# Calendar Agenda

Your day, from every calendar you keep, at the start of every session — and scheduling that
will not book you over a meeting sitting on a calendar you forgot to check.

```
📅  Today, Wednesday, 26 August · 4 events

   ⏰ 10:00–10:30  Warranty repair — service centre  🏠💼  📍 Denpasar
      16:15–16:45  Daily standup  💼  💻 Teams
      20:00–20:30  Status check  💼  💻 Teams
      20:30–22:00  Physio  🏠
```

## What it does

- **Session-start agenda.** A `SessionStart` hook reads every configured calendar and puts the
  day in the agent's context, so it already knows what your day looks like before you ask.
- **Any number of calendars.** Personal, work, a shared family one — each with its own badge.
- **Scheduling across all of them.** New events go only into slots free in *every* calendar.
- **Synced duplicates collapse.** If a tool copies your work meetings into your personal
  calendar as "Busy" or "Meeting", both lines fold into one, keeping the informative title.
- **Your timezone, automatically.** Unset means "wherever this machine is", so it keeps working
  when you travel. Override it if you would rather pin one.

## Install

```
/plugin marketplace add korkin25/agent-plugins
/plugin install calendar-agenda@korkin25
```

Then run the **`calendar-setup`** skill — just ask to set up the calendar integration. It walks
through the Google credentials, authenticates, asks which calendars to track and which one to
write to, and writes the config.

Requires `node`, `jq` and `npx` on `PATH`.

## Configuration

`~/.config/calendar-agenda/config.json`:

```jsonc
{
  "timeZone": null,          // null = this machine's zone
  "locale": null,            // null = system locale
  "calendars": [
    { "id": "you@gmail.com", "label": "personal", "badge": "🏠", "writable": true  },
    { "id": "you@work.com",  "label": "work",     "badge": "💼", "writable": false }
  ],
  "reminders": [             // optional; attached to events this plugin creates
    { "method": "popup", "minutes": 1440 },
    { "method": "popup", "minutes": 60 },
    { "method": "popup", "minutes": 5 }
  ]
}
```

Exactly one calendar should be `"writable": true`. `popup` reminders reach your phone; `email`
ones do not. Google allows at most five reminder overrides per event.

## Command line

```bash
calendar-agenda            # today
calendar-agenda --week     # the next seven days
calendar-agenda --json     # structured output
calendar-agenda --no-color # plain text
```

Colour is emitted only to a terminal, or when `CALENDAR_AGENDA_COLOR=1` is set — anything that
renders markdown would otherwise show escape codes literally.

## What this sends where

Worth knowing before you install it:

- **Your event titles go into the agent's context** at the start of every session. That is the
  point of the plugin, but it means the model — and whatever service runs it — sees the titles,
  times and locations of everything on the calendars you configure. Configure only calendars
  you are comfortable sharing that way.
- **Reads are read-only.** The agenda uses the `calendar.readonly` scope. Creating and changing
  events happens through the `google-calendar` MCP server, which asks for write access
  separately.
- **Credentials stay on your machine** — in `~/.config/google-calendar-mcp/`. This plugin reads
  them to talk to Google and never prints, copies or transmits them anywhere else.
- **A network call per session start.** The hook queries Google when a session begins; it fails
  quietly and never blocks the session.

## Authentication and the seven-day token

Setup uses a normal OAuth desktop client. While your Google Cloud consent screen is in
*Testing*, **Google invalidates the refresh token after seven days** and you have to
re-authenticate. That is Google's behaviour, not a bug here.

Publishing your app to production removes the limit, but Google requires a
Search-Console-verified domain plus home page, privacy and terms URLs — more than most personal
setups can provide.

A service account avoids the expiry entirely: its key does not expire, and you grant it access
by sharing a calendar with the service account's e-mail address, which works for ordinary
`@gmail.com` calendars without domain-wide delegation. That path needs
[nspady/google-calendar-mcp#192](https://github.com/nspady/google-calendar-mcp/pull/192) to land
upstream; this plugin already reads a service account key if it finds one, and support will be
completed in a release once the PR is merged.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `no configuration at …` | Setup was not finished — run the `calendar-setup` skill |
| `cannot read tokens` | The auth flow was never completed |
| `invalid_grant` | Token expired (the seven-day limit), or the consent screen was edited after it was issued — editing revokes existing grants |
| `unreachable <calendar>: notFound` | That calendar is not shared with the authenticated account |
| No agenda at session start | Hooks load when a session starts — restart it |

## Licence

MIT.
