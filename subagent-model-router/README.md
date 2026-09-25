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

Inherited models use the hook's session model, e.g. `model=gpt-6-astra (unchanged)`
(`unknown (unchanged)` if the host omits its model); unchanged Codex effort as `effort=unchanged`.
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

## What leaves the machine

For each routed launch, Jev receives the **entire subagent task and its description**, after masking known
credential formats. No TASK/ROLE extraction, summary or 1500-character truncation is performed. Multiline
instructions, permissions, checks, paths, repository names and other text in the task are included. The
plugin does not open referenced files or add conversation history. For Codex text-item calls, only text
items are included; attached images are not sent to Jev.

The combined task/description processing limit is 131072 Unicode characters. Above it the request is
rejected whole (`error:input_size`), with no Jev request and no model override; it is never silently shortened.
`input_quality` identifies full-text format version2 and whether masking occurred. Matching API tokens,
credentials, Authorization headers and private-key blocks are masked before transmission. Arbitrary secrets
or private prose may remain: masking is not a guarantee. Use project exclusions for tasks that must not leave
this machine. The `preview` tool shows exactly this filtered state locally, without a request or journal write;
the agent should use it when the user asks what will be sent, not automatically on every call.

OpenRouter/TypeSafe authentication goes only to the configured provider. Optional VM metrics contain
aggregate observations, project/user labels and reported costs, never full task text. Optional OpenRouter
balance polling uses the provider key only against the fixed OpenRouter key/credits API endpoints, in the
background, at most once per five minutes per installation while its worker runs. Key limits and account
credits are distinct; account usage may include other applications. The same account gauge reported by
several installations must be selected by freshest successful snapshot per alias, not summed.

## Monitoring

Claude Code and Codex on Linux and macOS can send the same operational metrics to VictoriaMetrics through a
configured endpoint. Python 3.11+ is required; no systemd/launchd service or extra Python package is needed.
Python collects and sends them automatically; no LLM turns or tokens are spent on telemetry. The synchronous
hook only updates private aggregate state and starts one background sender, so VM latency/outages do not
hold up model selection. The local JSONL journal stops growing in VM mode; a bounded aggregate delivery buffer
remains for counters and retries. `SessionStart` and `UserPromptSubmit` hooks also start that sender (silently,
without a network call or a write), so delivery resumes after a client restart, not only at the next subagent.

The metrics cover Jev latency/errors, model/tier/effort choices, active versus shadow decisions and decision
probabilities, with project, user and Claude/Codex cohorts. Grafana filters and compares these cohorts;
Ask the agent to select a project, user or client for a report. Terminal and VS Code extensions share this hook. They measure routing behavior, not demonstrated cost savings or task quality.

- [Setup, delivery limits and commands](skills/subagent-model-router/references/monitoring.md)
- [Importable Grafana dashboard](grafana/subagent-model-router.json)
- Ask for statistics: the agent displays a formatted dashboard directly in its reply.
- Ask to open the dashboard: the agent opens a temporary in-memory page in an available browser.
- Ask about delivery health: the agent checks local pending delivery/error state.

VM errors are reported as errors; there is no silent fallback to old local statistics. Existing JSONL history
is preserved and is not automatically exported. Configure a unique stable instance label for each writer.

## How to turn it off

- For some projects: `exclude = ["~/work/secret"]` — directories and everything inside them; no request at all is
  made from there. Directory names are compared whole: `~/work/secret` does not cover `~/work/secret.old`.
- Entirely: `enabled = false` in the config, or uninstall the plugin.
- Watch without changing anything: `mode = "shadow"` — requests are made and decisions are journalled, but
  no subagent call is modified.

## Install and use through Claude Code or Codex

Paste this request into your Claude Code or Codex chat (terminal or VS Code):

> Install subagent-model-router from https://github.com/korkin25/agent-plugins for this user.
> Configure OpenRouter using my existing key file at [path to file]; do not display its contents.
> Preserve my current settings, trust only this plugin's Codex hook if needed, and check the setup.

The agent performs installation and setup. You do not need to find the plugin cache, change directories or
run terminal commands. Python 3.11+ is required. Supply a path to an existing private key file, not the key
itself in the conversation. After installation, start a new session so the client loads the plugin.

Once installed, ask naturally:

- **“Show router statistics for the last seven days.”** — a dashboard directly in the answer, with counts,
  latency, model distributions, project/user/client breakdowns and compact trend charts.
- **“Compare Codex and Claude for project X.”** — the agent uses the stored client/project cohorts.
- **“Open the router dashboard in the browser.”** — the same snapshot in the available in-app browser,
  with the default desktop browser as a fallback. HTML is served from memory on a short-lived local URL,
  not saved to a fixed file. A remote/headless session still shows the dashboard in chat.
- **“Connect VictoriaMetrics at [URL].”** — the agent configures the endpoint; a token-file path is optional.

The agent-side installation and diagnostic commands are documented in
[the skill](skills/subagent-model-router/SKILL.md); they are implementation details, not steps for the user.

## Keys

- **TypeSafe**: [console.typesafe.ai/keys](https://console.typesafe.ai/keys). Access may start with a waitlist.
- **OpenRouter**: [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys), with
  `provider = "openrouter"` in the config.

## Configuration

`~/.config/subagent-model-router/config.toml` (directory 0700, file 0600; `SUBAGENT_MODEL_ROUTER_CONFIG`
overrides the path). [`config.example.toml`](config.example.toml) lists every key with its default. An unknown
key, a bad value, or a file writable by others turns the hook off with `error:config` in the journal; `check`
says what is wrong.

## Agent implementation commands

These commands are run by Claude/Codex on the user's behalf, not copied to the user as instructions.

```bash
subagent-model-router check [--live]          # config, key, models, codex catalog (fetched now, ≤ 30 s)
subagent-model-router explain "TASK: …"       # what Jev answers for a task and which model follows
subagent-model-router stats [--days N]        # decisions from the journal
subagent-model-router codex-trust [--codex PATH] [--dry-run]
```

`explain` makes a real request, so the text goes to TypeSafe or OpenRouter just as the hook would send it.

## Money

Router requests export provider-reported cost, known-cost coverage and token counts by cohort. Optional
background OpenRouter polling shows remaining key limit and account credit balance separately, with age and
probe status. Ask the agent to enable balance monitoring; the existing provider key stays private. Several
installations using one key do not multiply its account balance. Unpriced/failed requests remain unknown.

## Evaluation

A frozen 28-case synthetic old-versus-full-text comparison (112 requests) is in
[the evaluation report](eval/results-20260925.md). Full text preserved more input but did not improve final
routing accuracy on this set; API-reported cost increased 9.4%. This does not measure downstream quality or savings.

## Limitations

- English is Jev's main language; the questions are asked in English, and accuracy on tasks written in other
  languages has not been measured.
- Jev reads literally: it judges what the filtered description and full task say, not what was meant.
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
