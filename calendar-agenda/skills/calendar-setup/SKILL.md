---
name: calendar-setup
description: First-run setup for the calendar-agenda plugin — connect Google Calendar, choose which calendars to track and which one to write to, and write the config file. Use when the plugin reports it is not configured, when the user wants to add or remove a calendar, or when they ask to set up the calendar integration.
---

# Setting up calendar-agenda

Goal: a working `~/.config/calendar-agenda/config.json` and an authenticated
`google-calendar` MCP server. Walk the user through it; do not do the parts that are theirs.

**Never handle their credentials.** You may create directories, write the config and set file
permissions. You may not enter passwords, complete Google's consent screen, or read the
contents of a credentials file — checking which top-level keys it contains is enough to tell an
OAuth client from a service account key.

## 1. Google Cloud credentials

The user does this in their own browser:

1. Create (or pick) a project at <https://console.cloud.google.com>.
2. Enable the **Google Calendar API** for it.
3. Configure the OAuth consent screen: app name, support e-mail, developer contact. Leave the
   home page / privacy / terms links empty — filling any of them forces an authorized-domain
   requirement that a personal setup cannot satisfy.
4. Add their own address under **Audience → Test users**.
5. Create credentials → OAuth client ID → application type **Desktop app** → download the JSON.

Then place it, mode 600:

```bash
mkdir -p ~/.config/google-calendar-mcp
mv ~/Downloads/client_secret_*.json ~/.config/google-calendar-mcp/gcp-oauth.keys.json
chmod 600 ~/.config/google-calendar-mcp/gcp-oauth.keys.json
```

Verify the shape without reading secrets — `['installed']` means Desktop app, which is what the
auth flow expects; `['web']` is the wrong client type:

```bash
python3 -c "import json;print(list(json.load(open('$HOME/.config/google-calendar-mcp/gcp-oauth.keys.json')).keys()))"
```

## 2. Authenticate

```bash
GOOGLE_OAUTH_CREDENTIALS=~/.config/google-calendar-mcp/gcp-oauth.keys.json \
GOOGLE_CALENDAR_MCP_TOKEN_PATH=~/.config/google-calendar-mcp/tokens.json \
npx -y @cocal/google-calendar-mcp@2.6.2 auth
```

A browser opens; **the user** picks the account and accepts. Google will warn that the app is
unverified — expected for a personal client: *Advanced → Go to …*.

**Tell them about the seven-day limit up front**, because it looks like a breakage later: while
the consent screen is in *Testing*, Google invalidates the refresh token after a week and the
same command has to be run again. Publishing the app to production removes that, but Google
requires a Search-Console-verified domain plus home page, privacy and terms URLs, which most
personal setups cannot supply.

## 3. Choose the calendars

Ask which calendars to track, and which single one new events should be created in. Get the
real ids rather than guessing — a calendar id is usually its address:

```bash
npx -y @cocal/google-calendar-mcp@2.6.2 --version >/dev/null 2>&1  # ensure it is fetched
```

then use the `list-calendars` tool of the `google-calendar` MCP server, and confirm the list
with the user before writing anything.

## 4. Write the config

```jsonc
{
  "timeZone": null,          // null = this machine's zone; keeps working when travelling
  "locale": null,            // null = system locale
  "calendars": [
    { "id": "you@gmail.com",   "label": "personal", "badge": "🏠", "writable": true  },
    { "id": "you@work.com",    "label": "work",     "badge": "💼", "writable": false }
  ],
  "reminders": [
    { "method": "popup", "minutes": 1440 },
    { "method": "popup", "minutes": 60 },
    { "method": "popup", "minutes": 5 }
  ]
}
```

Write it to `~/.config/calendar-agenda/config.json`. Exactly one calendar should have
`"writable": true`. `reminders` is optional; when present the `calendar-event` skill attaches
that set to every event it creates.

## 5. Check it

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/calendar-agenda"
```

It should print today's agenda. Then **restart the session** so the `SessionStart` hook is
picked up — hooks load at session start, so the current session will not have it.

## When it does not work

- **"no configuration at …"** — step 4 was not done, or the path is wrong.
- **"cannot read tokens"** — step 2 was not completed.
- **`invalid_grant`** — the token expired (the seven-day limit) or the consent screen was edited
  after the token was issued; editing it revokes existing grants. Re-run step 2.
- **A calendar shows `unreachable … notFound`** — that calendar is not shared with the
  authenticated account. Sharing is done by its owner, in Google Calendar's settings for that
  calendar.
- **Escape codes such as `[1m[36m` in the output** — something is rendering the agenda as
  markdown. The bundled hook already avoids this; a hand-written one should not set
  `CALENDAR_AGENDA_COLOR=1`.
