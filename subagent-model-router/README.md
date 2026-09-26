# Subagent Model Router

Jev (TypeSafe AI) directly selects a model and effort for eligible subagents from their task text — in
Claude Code and in Codex — while your main session stays on the model you picked.

## What it does

Version 0.5.0 asks Jev to choose **one concrete model and effort candidate** for each eligible task.
The `PreToolUse` hook watches `Agent` in Claude Code and `spawn_agent` in Codex
(`collaborationspawn_agent` under multi-agent v2). Jev receives the available candidates and the filtered
full task, then selects the pair directly. There are no task tiers, risk/review classifiers, probability
thresholds or parent-model lookups.

- **Codex:** candidates come from the cached native catalog of the client that runs the session.
  Only visible models and their supported efforts are offered, with the client's model-purpose and effort
  descriptions. Optional `codex.allowed_models` narrows the list; an empty list includes all eligible models.
- **Claude Code:** candidates come from the native SDK initialization model catalog, including its model
  descriptions and supported efforts. `claude.allowed_models = []` offers every supported Agent alias found
  there (`haiku`, `sonnet`, `opus`, `fable`); `claude.efforts = []` offers all levels that model supports.
  Nonempty lists restrict those candidates. Models without effort support use null effort.

Jev receives shared purpose and price metadata once per model, with each candidate's effort explanation,
so it does not have to infer capabilities from an unfamiliar model name. Claude effort explanations use the official
[effort-level guidance](https://code.claude.com/docs/en/model-config#choose-an-effort-level); native metadata
controls which levels are offered. Refreshing catalogs uses client metadata, with no LLM research jobs.
The selection instruction puts task adequacy first, then prefers the lowest documented applicable API
cost among adequate models and the lowest sufficient effort supported by that model. Straightforward tasks
default to that model's lowest supported effort unless a concrete requirement calls for more.
The hook script builds the request, reads cached metadata, calls Jev and applies the returned choice
deterministically. The parent model does not prepare this JSON or run a separate model to estimate costs.
Jev's API request itself still consumes provider tokens and can incur charges.

For Claude, the hook sets `model` explicitly. Effort is applied through a bundled native agent definition:
for example, `subagent_type: "subagent-model-router:effort-high"` selects frontmatter `effort: high`.
`Agent` has no direct effort parameter. The five bundled definitions omit `model` and share the same generic
instructions to respect the delegated task's scope. Per-call model selection takes precedence over the
definition. See [Claude subagent frontmatter](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields)
and [model precedence](https://code.claude.com/docs/en/sub-agents#choose-a-model).

The hook leaves these calls unchanged:

- calls with an explicit model or reasoning effort;
- Claude specialized agents, including `Explore`, `Plan`, custom agents and forks;
- Codex full-context forks: `fork_turns` other than `"none"` (its default is `all`), or `fork_context: true`;
- Codex roles outside `codex.route_agent_types` (default: no role, `default`, `worker`);
- Claude launches subject to native model/effort environment overrides, including custom model alias pins,
  that would conflict with the isolated catalog;
- excluded projects, disabled routing, missing configuration/key, unusable catalogs, invalid choices,
  request errors and timeouts. The hook exits successfully without rewriting the call and records the reason.

A permitted Codex role can still impose its own model. Claude environment/policy limits and model support
can also constrain execution. A submitted candidate is not proof of the model or effort actually used.

Model-purpose descriptions have no time expiry and are reused while the available model identities remain
known. Discovery stays separate: each Codex launch checks the native binary and `CODEX_HOME/models_cache.json`
file metadata for changes and starts an asynchronous catalog probe when needed. Claude checks binary identity
on each launch and probes native metadata asynchronously at every `SessionStart`. An allowlist entry missing
from the catalog also requests a new probe. These checks do not run a synchronous client process per subagent.

A new model identity or missing purpose description triggers metadata refresh and a refresh of prices for
the entire available inventory, including models that still lack descriptions. Undescribed models are not
offered to Jev. Without a usable catalog, there is no routing request or rewrite. Run `check` after installation
to fetch both catalogs; each native probe has a 30-second bound. `codex_bin` and `claude_bin` optionally identify
a client when it cannot be found from the invoking process or absolute PATH entries.

Claude refresh sends only an SDK `initialize` control request, with no user message or model turn. It runs
in a private temporary directory with isolated HOME/config, empty MCP configuration, hooks disabled through
`--bare`, and no inherited credential environment variables. Only allowlisted model metadata is cached;
account fields are discarded. The native client may perform metadata I/O; this is not a model request.

A catalog entry such as `opus[1m]` can describe the `opus` candidate when no canonical alias row exists.
Its resolved model ID and catalog spelling are descriptive provenance. The launch still submits `opus`;
neither the exact model revision nor the context size is guaranteed by that catalog observation.

Jev also receives official API price references in USD per million tokens from
[OpenAI](https://developers.openai.com/api/docs/pricing) and
[Anthropic](https://platform.claude.com/docs/en/about-claude/pricing). These are standard API rates,
including separate input, output, cache-read and cache-write rates where published. OpenAI short and long
context rates remain separate; Claude distinguishes five-minute and one-hour cache writes. A price is
attached only when the native model ID has an exact official match. Missing prices remain unknown and
do not remove an otherwise eligible candidate.

Price refresh runs in the background after 24 hours and immediately when a newly available model needs
metadata; it refreshes prices for all models in that client's catalog. Failed refreshes retain previous
prices with an explicit stale label. These references are not subscription costs, the child's actual bill,
or measured savings. Prices can change without a new model ID, so their freshness is independent of the
reused model-purpose descriptions.

Jev receives the visible task's approximate token count and an estimated uncached input cost for each
model. The script uses `ceil(UTF-8 bytes / 4)` on the filtered task and description; this is a coarse local
heuristic, not a verified GPT-6 or Claude tokenizer. Hidden child instructions, tool definitions, prior
context and future output remain unknown. Standard and long-context input estimates stay separate because
the full request's context band is unknown. These estimates do not replace Jev's reported usage or charges.
No extra API request or parent-model call is made to calculate them.

### Model notice before launch

After a valid choice, synchronous `PreToolUse` emits a user-facing `systemMessage` in both clients:

```text
subagent-model-router: "find_readme" — selected for launch: model=haiku; choice
subagent-model-router: "list_toml" — selected for launch: model=gpt-5.6-luna, effort=low; choice
```

The notice describes selected launch parameters, not successful execution. Shadow mode labels the choice
as a recommendation and leaves all launch arguments unchanged. Skipped calls and request failures remain
silent; their reasons are available in statistics. The label is redacted, stripped of control characters,
and bounded to 120 characters; task text is not shown. No extra model request is made for the notice.

Routing does not read conversation transcripts, parent-turn metadata, or lifecycle model checkpoints.
The retained `claude-session` command initializes client-version metadata at `SessionStart`; it does not
track the session model. Session start also requests background native catalog discovery. Version detection
and update notices remain separate from model selection.

The notice uses the common [`systemMessage` hook field in Claude Code](https://code.claude.com/docs/en/hooks)
and [Codex](https://developers.openai.com/codex/hooks). Rendering depends on the client; Codex surfaces it
as a UI/event-stream warning, so a separate chat message in every terminal, IDE and app is not guaranteed.

### Updates in an open session

From 0.4.8, a synchronous hook checks for a newer installed version at session start and on user prompts.
It compares the version of its executing plugin copy with native installed-plugin metadata and emits a
`systemMessage` once per session and observed installed version. This is local Python/CLI work, with no
model request or added conversation context. It does not install updates or schedule an updater.
Missing or ambiguous installation evidence stays silent. A session still running 0.4.7 lacks this checker
and needs an initial reload/new session before it can report later updates.

In [Claude Code](https://code.claude.com/docs/en/discover-plugins), `/reload-plugins` applies plugin changes
without ending the session. Claude can defer reload to preserve a warm prompt cache; forcing it with
`/reload-plugins --force` can cost an uncached request. The router never forces reload and does not account
for that conversation cost. In [Codex](https://learn.chatgpt.com/docs/plugins), start a new session after
updating the plugin and review changed hooks in `/hooks` if requested. Automatic discovery of local skill
changes does not prove that new hooks are loaded or trusted. Notifications describe the executing hook,
not every component of the session. UI rendering depends on the host.

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
aggregate observations, host/project/user/client and version labels, and reported costs, never full task text. Optional OpenRouter
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

The metrics cover Jev latency/errors, model/effort choices and active versus shadow decisions, with
project, user and Claude/Codex cohorts. Reports also show observed hook/plugin and client
versions by host and user, plus the last actual hook observation. Client version is captured once at
session start and read from a private session cache during routing. A worker heartbeat does not refresh that
observation. Missing, idle or older unversioned reporters remain unknown; this is not an inventory proving
that every installation updated. Grafana filters and compares these cohorts;
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

Known legacy tier tables, thresholds and transcript-observation settings are accepted but ignored in 0.5.0;
`check` reports migration warnings. Remove those obsolete fields when updating the config. Preserve existing
provider, key-file, exclusion and telemetry settings. Unknown keys remain errors.

## Agent implementation commands

These commands are run by Claude/Codex on the user's behalf, not copied to the user as instructions.

```bash
subagent-model-router check [--live]          # config, key, native client catalogs (≤ 30 s per refresh)
subagent-model-router explain --agent codex "TASK: …"  # direct candidate selection for one client
subagent-model-router stats [--days N]        # decisions from the journal
subagent-model-router codex-trust [--codex PATH] [--dry-run]
```

`explain` makes a real request, so the text goes to TypeSafe or OpenRouter just as the hook would send it.

## Money

Router requests export provider-reported cost, known-cost coverage and input/output token counts with
separate coverage for each direction. Unpriced/failed requests remain unknown. Optional background
OpenRouter polling shows remaining key limit and account credit balance separately, with age and probe
status. Ask the agent to enable balance monitoring; the provider key stays private. Several installations
using one key do not multiply its account balance. Forced Claude plugin reload can invalidate the prompt
cache; that conversation cost is outside the router's Jev accounting.

## Evaluation

The [historical evaluation report](eval/results-20260925.md) compares the old classifier's truncated and
full-text inputs. It does not evaluate 0.5.0 direct candidate selection, downstream quality or savings.

## Limitations

- Jev selects from the task text and offered candidates; vague tasks and model capability assumptions can
  produce poor choices. Language-specific accuracy and downstream quality are not established.
- Claude aliases select a model family, not a guaranteed version. Native environment overrides, policy
  caps and model support can affect execution. A server-side Claude catalog change may remain unseen until
  the next session or explicit check when the native binary stays unchanged.
- Native metadata determines effort support. Do not report a null effort as a chosen low effort.
- Each routed start makes one logical request, possibly with one internal retry, within the configured
  timeout budget (3 seconds by default), and may incur provider charges.
- Historical data is preserved; obsolete classifier and local-lookup metrics are not shown in the main
  dashboard and are not retroactively converted into direct choices.

## Tests

```bash
python3 -B -m unittest discover -s tests
python3 -B tests/run_parallel.py -j 4     # the same tests, one process per test class
```

Standard library only; the Jev server and the `codex` program are faked, nothing leaves the machine.

## Licence

MIT.
