# Subagent Model Router

Every subagent gets a model that fits its task, chosen by Jev (TypeSafe AI) from the text of that task — in
Claude Code and in Codex — while your main session stays on the model you picked.

A simple "list the `*.toml` files" helper runs on a small, fast model; ordinary engineering work on a mid-size
one; reviews, risky changes and anything Jev is unsure about stay on your session model.

## What it does

A `PreToolUse` hook watches the tool that starts a subagent: `Agent` in Claude Code, `spawn_agent` in Codex
(`collaborationspawn_agent` under multi-agent v2). Before the subagent starts, the hook asks Jev three
questions about its task — how demanding it is (`light` / `standard` / `heavy`), whether a mistake could do
damage (`risky`), and whether it is a review of someone else's finished work (`review`) — and maps the answer
to a model:

| Tier | Claude Code | Codex |
|---|---|---|
| light | `haiku` | `gpt-5.6-luna`, effort `low` |
| standard | `sonnet` | `gpt-5.6-terra`, effort `medium` |
| heavy, risky, review, unsure | session model | session model and effort |

The mapping and the thresholds live in the config. What the hook leaves alone:

- a call that already names a model (or, in Codex, a reasoning effort);
- in Claude Code, subagent types other than `general-purpose` (configurable) — `Explore`, `Plan`, your own
  agents, forks;
- in Codex, full forks of the conversation — `fork_turns` other than `"none"` (the default is `all`), or
  `fork_context: true` — because a fork carries the parent's context and belongs on the parent's model;
- in Codex, roles (`agent_type`) outside `[codex] route_agent_types` (by default: no role, `default`,
  `worker`) — such a role may set its own model, and the effort would be checked against the wrong one;
- anything that goes wrong: no config, no key, network trouble, a slow or odd answer. The hook exits 0 with no
  output, the subagent starts as usual, and the reason goes to the journal.

In Codex the model and effort are checked against the model catalog of the codex binary that runs the session
before they are set, because Codex refuses to start a subagent on an unknown model or an unsupported effort.
A model missing from the catalog, or an effort the resulting model does not support, is simply not set.

The hook never waits for `codex debug models`, which can take seconds when Codex fetches the catalog over the
network. It reads the catalog from its own cache — fresh for 24 hours, still used up to 7 days old — and
refreshes an old or missing one in a background process. Until a first refresh has finished, Codex subagents
get neither model nor effort, so run `check` once after installing: it fetches the catalog and fills the
cache.

### Model notice before launch

After Jev answers, the synchronous `PreToolUse` hook emits a user-facing `systemMessage` in both Claude Code
and Codex, alongside any argument changes. For example:

```text
subagent-model-router: "find_readme" — selected for launch: model=haiku; rule:light
subagent-model-router: "list_toml" — selected for launch: model=gpt-5.6-luna, effort=low; rule:light
```

Inherited models are shown as `model=session (unchanged)`; unchanged Codex effort as `effort=unchanged`.
Catalog restrictions are included in the notice, so an unavailable model is never advertised as selected.
Shadow mode says `shadow recommendation` and `launch arguments unchanged`. Disabled, excluded, explicit,
forked or unsupported calls and request failures remain silent. There is no extra network request.

The label is redacted, stripped of control characters and limited to 120 characters; task text is not shown.
The message reports the router's selection before launch, not successful execution; a Codex role's own model
can still override it. This uses the common [`systemMessage` hook field in Claude Code](https://code.claude.com/docs/en/hooks)
and [Codex](https://developers.openai.com/codex/hooks), not model-only `additionalContext`.
Rendering depends on the client: Codex surfaces it as a warning in the UI or event stream; a separate chat
message and identical display in every terminal, IDE and app are not guaranteed.

## Why only subagents

The prompt cache belongs to a model. Switching the main session's model on every message would throw away the
cache of the whole conversation and cost more than it saves. A subagent starts from a clean context, so
choosing its model at start-up loses nothing.

## What this sends where

- **One request per subagent start** to TypeSafe (`https://api.typesafe.ai/v1/systemone`, the default) or to
  OpenRouter (`https://openrouter.ai/api/alpha/decisions`, with `provider = "openrouter"`). The request holds
  the subagent's short description (Claude Code `description`, Codex `task_name` or role) and the task lines
  that start with `TASK:` and `ROLE:` — or the first 1500 characters of the task when it has no such lines.
  Common credential formats are masked with `[redacted]` before sending: GitLab (`glpat-…`), GitHub
  (`ghp_…`, `gho_…`, `github_pat_…`), `sk-…`, Slack (`xox?-…`), AWS (`AKIA…`) and Google (`AIza…`) keys,
  JWTs, `PRIVATE KEY` blocks, `Bearer` and `Authorization: Basic` credentials, `user:password@` in URLs,
  `--password <value>`, and values after `password`, `passwd`, `token`, `secret`, `api_key`/`api-key` (so
  `X-Api-Key:` too) with `:` or `=`. Do not rely on it for anything else: a secret in any other form is sent
  as written. Nothing else of the task, no files and no history leave the machine.
- **The key** stays in a file on your machine and goes only into the `Authorization` header of that request —
  over https, and never along a redirect.
- **Statistics** use a local decision journal by default. Optional VictoriaMetrics mode sends only aggregate
  metrics and stops appending the journal; see Monitoring below.
- **In Codex**, a background process runs `codex debug models` of the codex binary that runs the session when
  the cached catalog is missing or older than 24 hours — one at a time, for at most 30 seconds — and caches
  the catalog in `~/.cache/subagent-model-router/codex-models.json`, keyed by the binary's real path and
  modification time. `codex-trust` talks to your local `codex app-server` and
  writes only the trust entries of this plugin's hooks into your Codex configuration.

## Monitoring

Claude Code and Codex on Linux and macOS can send the same operational metrics to VictoriaMetrics through a
configured endpoint. Python 3.11+ is required; no systemd/launchd service or extra Python package is needed.
Python collects and sends them automatically; no LLM turns or tokens are spent on telemetry. The synchronous
hook only updates private aggregate state and starts one background sender, so VM latency/outages do not
hold up model selection. The local JSONL journal stops growing in VM mode; a bounded aggregate delivery buffer
remains for counters and retries.

The metrics cover Jev latency/errors, model/tier/effort choices, active versus shadow decisions and decision
probabilities, with project, user and Claude/Codex cohorts. Grafana filters and compares these cohorts;
`stats --project NAME --user NAME` selects them for a report. Terminal and VS Code extensions share this hook. They measure routing behavior, not demonstrated cost savings or task quality.

- [Setup, delivery limits and commands](skills/subagent-model-router/references/monitoring.md)
- [Importable Grafana dashboard](grafana/subagent-model-router.json)
- `stats --days 7 --html /path/to/router-dashboard.html`: standalone dashboard snapshot from VM.
- `stats --days 7 --json`: compact summary for Claude/Codex to interpret.
- `telemetry-status`: inspect local pending delivery/error state without contacting VM.

VM errors are reported as errors; there is no silent fallback to old local statistics. Existing JSONL history
is preserved and is not automatically exported. Configure a unique stable instance label for each writer.

## How to turn it off

- For some projects: `exclude = ["~/work/secret"]` — directories and everything inside them; no request at all is
  made from there. Directory names are compared whole: `~/work/secret` does not cover `~/work/secret.old`.
- Entirely: `enabled = false` in the config, or uninstall the plugin.
- Watch without changing anything: `mode = "shadow"` — requests are made and decisions are journalled, but
  no subagent call is modified.

## Install

The plugin is installed for your user, not per project, and then works in every project. Each user on a
machine has their own config and key in `~/.config/subagent-model-router/`. Python 3.11 or newer is required
(standard library only).

**Claude Code**

```
/plugin marketplace add korkin25/agent-plugins
/plugin install subagent-model-router@korkin25
```

**Codex**

```bash
codex plugin marketplace add korkin25/agent-plugins
codex plugin add subagent-model-router@korkin25
<plugin dir>/bin/subagent-model-router codex-trust   # once: Codex runs a plugin hook only after it is trusted
```

The command lives in the plugin's `bin/` directory. Claude Code puts it on the `PATH` of its Bash tool, so
there it is just `subagent-model-router`; in a terminal or in Codex call it by its full path inside the
installed plugin directory, shown here as `<plugin dir>`. `codex-trust` does what the `/hooks` screen in Codex
does, through Codex's own app-server (`hooks/list`, then `config/batchWrite` of `hooks.state` — the same
calls, unchanged between Codex 0.153.4 and 0.154.0): it marks this plugin's hooks trusted and touches nothing
else. A hook counts as this plugin's only when Codex lists it for a plugin named `subagent-model-router` and
its command is exactly `…/bin/subagent-model-router hook`; hooks that do not come from a plugin are never
trusted. `--dry-run` shows what it would trust; `--codex PATH` names the codex binary when `codex` is not on
`PATH` (otherwise it uses `codex_bin` from the config, then `PATH`; only absolute `PATH` entries count). A
Codex version whose app-server speaks a different protocol gets a refusal rather than a guess — trust the hook
in `/hooks` by hand then. Trust is tied to the hook definition, not to the install path, so it survives plugin
updates that leave `hooks/hooks.json` as it is; if Codex ever shows the hook as modified, run `codex-trust`
again.

Then create the config and the key:

```bash
install -d -m 700 ~/.config/subagent-model-router
install -m 600 <plugin dir>/config.example.toml ~/.config/subagent-model-router/config.toml
( umask 077; cat > ~/.config/subagent-model-router/key )   # paste the key, Enter, Ctrl-D
<plugin dir>/bin/subagent-model-router check                # also fills the Codex model catalog cache
```

Installing for another account with `sudo -u <user>`, run the `codex plugin` commands from that account's home
directory, for example `sudo -u <user> -H sh -c 'cd && codex plugin add subagent-model-router@korkin25'`.
Otherwise Codex reads `.codex/config.toml` of the current directory as a project layer and may fail on its
permissions.

The key file must be a single line owned by you with permissions 0600 or 0400; otherwise the hook treats it
as missing.

### VS Code

The Claude Code and Codex extensions for VS Code use the same `~/.claude` and `~/.codex` as the command-line
tools, so a plugin installed for your user works there too. The Codex extension brings its own `codex`
binary, which is often not on `PATH`:

```bash
ls -d ~/.vscode/extensions/openai.chatgpt-*/bin/*/codex ~/.cursor*/extensions/openai.chatgpt-*/bin/*/codex 2>/dev/null
```

Trust the hook with that binary: `subagent-model-router codex-trust --codex <that path>`. The hook itself
finds the binary on its own and uses the catalog of the codex that runs it: the `codex` process that started
the hook, then `codex_bin` from the config, then `codex` on `PATH` (absolute entries only). Setting
`codex_bin` to the extension's path is possible, but that path changes with every extension update.

## Keys

- **TypeSafe**: [console.typesafe.ai/keys](https://console.typesafe.ai/keys). Access may start with a waitlist.
- **OpenRouter**: [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys), with
  `provider = "openrouter"` in the config.

## Configuration

`~/.config/subagent-model-router/config.toml` (directory 0700, file 0600; `SUBAGENT_MODEL_ROUTER_CONFIG`
overrides the path). [`config.example.toml`](config.example.toml) lists every key with its default. An unknown
key, a bad value, or a file writable by others turns the hook off with `error:config` in the journal; `check`
says what is wrong.

## Commands

```bash
subagent-model-router check [--live]          # config, key, models, codex catalog (fetched now, ≤ 30 s)
subagent-model-router explain "TASK: …"       # what Jev answers for a task and which model follows
subagent-model-router stats [--days N]        # decisions from the journal
subagent-model-router codex-trust [--codex PATH] [--dry-run]
```

`explain` makes a real request, so the text goes to TypeSafe or OpenRouter just as the hook would send it.

## Limitations

- English is Jev's main language; the questions are asked in English, and accuracy on tasks written in other
  languages has not been measured.
- Jev reads literally: it judges what the description and the `TASK:`/`ROLE:` lines say, not what was meant.
  A short or vague task gives an unsure answer, which means the session model.
- In Codex only the roles in `route_agent_types` are routed; if such a role's file sets its own model, that
  model wins over the choice.
- In Claude Code only the model is chosen: the `Agent` call has no effort parameter.
- Each subagent start costs a request — usually well under a second, never longer than the budget
  (`timeout_seconds`, 3 s by default) — and a small amount of money.

## Tests

```bash
python3 -B -m unittest discover -s tests
python3 -B tests/run_parallel.py -j 4     # the same tests, one process per test class
```

Standard library only; the Jev server and the `codex` program are faked, nothing leaves the machine.

## Licence

MIT.
