---
name: subagent-model-router
description: Jev (TypeSafe AI) directly picks a model and effort for eligible subagents from the text of its task, in Claude Code and in Codex, while the main session keeps the model chosen by hand. Use when the user asks which models subagents were given, why a task got a particular model, to turn model routing on or off, to switch it to observe-only (shadow) mode, to set up or check the TypeSafe or OpenRouter key, to exclude directories, to trust the hook in Codex, or to configure VictoriaMetrics monitoring and show router statistics/dashboards. Also triggers on «какие модели выбирались субагентам», «почему субагенту такая модель», «включи выбор модели», «выключи выбор модели», «режим наблюдения», «настрой ключ», «доверь хук в Codex».
---

# Subagent Model Router

A `PreToolUse` hook on the tool that starts a subagent — `Agent` in Claude Code, `spawn_agent` in Codex.
Version 0.5.0 asks Jev for one choice from concrete model/effort candidates for the task. It submits that
choice as native launch parameters. The main session is never touched.

## User interaction

Users ask in their Claude/Codex chat; they do not run shell commands or locate plugin files. Perform setup,
checks and statistics retrieval yourself with tools. Resolve the plugin root from this SKILL.md location
(two directories above), use its absolute `bin/subagent-model-router` path, and quote paths. Never tell the
user to run `./bin/...` from an unspecified directory or paste a versioned cache path as the normal workflow.

For an installation request, install `subagent-model-router@korkin25` from `korkin25/agent-plugins` with the
host's plugin manager. Claude Code: run `claude plugin marketplace add korkin25/agent-plugins` and
`claude plugin install subagent-model-router@korkin25`. Codex: use `codex plugin marketplace add` and
`codex plugin add` with the same arguments. Discover the resulting root; do not guess its version/path.
Preserve existing settings. Both terminal and VS Code use the account's plugin storage; if the Codex CLI is
not on PATH, use the installed extension's binary. Run per-user commands from that user's home.

## Direct selection and native launch parameters

Jev chooses one offered model/effort pair. No tier/risk/review classifier, thresholds, parent model
inheritance or transcript lookup participates in routing. Do not inspect conversation history to fill
missing model labels. Skips and missing evidence remain distinct from a successful choice.
Model-purpose and price metadata are shared once per model; candidates carry the applicable effort
explanation without repeating the complete model description and tariff for every effort level.
The script constructs and submits the Jev request and applies its choice; do not add parent-model work
to build JSON, research model descriptions or calculate consumption estimates. Jev's own API usage still
incurs provider tokens and any applicable charges.

Claude Code:
- Route generic `Agent` calls only, respecting `claude.route_types` (default `general-purpose`). Preserve
  specialized agents, explicit choices and forks rather than replacing their prompts or tool permissions.
- Claude candidates use the native SDK model catalog's purpose descriptions and effort support.
  `claude.allowed_models = []` includes every supported Agent alias found there (`haiku`, `sonnet`, `opus`,
  `fable`); `claude.efforts = []` includes every reported supported effort. Nonempty lists narrow candidates.
  A native no-effort model uses null effort. Never infer support or purpose from a model's name alone.
- Effort-purpose descriptions come from the official Claude effort-level table; availability comes from
  the native catalog. Descriptions guide Jev directly, without tiers or a second research-model call.
- Set `updatedInput.model` to the selected alias. For supported effort set `subagent_type` to
  `subagent-model-router:effort-<level>`. Bundled definitions set frontmatter `effort` and omit `model`.
  Copy every other input field. There is no direct `Agent.effort` parameter and no `permissionDecision`.
- Native model/effort environment overrides, including custom `ANTHROPIC_DEFAULT_*_MODEL` pins, cause
  a skip with a recorded reason because the isolated catalog cannot describe that custom mapping. Policy caps, aliases
  resolving to particular versions and subsequent execution can still affect the actual result.

Codex:
- Route `spawn_agent` and `collaborationspawn_agent`; preserve explicit `model`/`reasoning_effort`, full
  forks (`fork_turns` other than `"none"`, including its omitted default, or `fork_context: true`) and
  roles outside `codex.route_agent_types` (default no role, `default`, `worker`).
- Build candidates from visible entries in the cached actual-client model catalog, each model's native
  purpose description, and every supported effort with its native description. `codex.allowed_models = []` offers all supported models; a nonempty list narrows them.
- Resolve the actual invoking binary first, then configured `codex_bin`, then absolute PATH entries.
  Each launch checks binary identity and file metadata of `CODEX_HOME/models_cache.json`; a changed
  fingerprint triggers a background native probe, bounded to 30 seconds. A missing allowlist model also
  requests a probe. With no usable catalog, skip the Jev call and rewrite. `check` fills the cache now.
- Set the chosen `model` and `reasoning_effort` with `permissionDecision: "allow"` and complete
  `updatedInput`, as required by the Codex hook contract. A role's own model may override these parameters.

Catalog refresh for Claude:
- Resolve the invoking native executable first, then `claude_bin`, then absolute PATH entries. Cache entries
  use real path/mtime. Check binary identity per launch and run asynchronous SDK discovery on every
  `SessionStart`; do not start a synchronous Claude process for each Agent call. A missing allowlist model
  also requests a probe. An upstream change within an unchanged binary/session can remain unseen until
  the next session or explicit `check`. Without a usable catalog, preserve the original launch.
- Send only SDK `initialize` in a private temporary HOME/CLAUDE_CONFIG_DIR with `--bare`, no user/model turn,
  no inherited credential environment, and strict empty MCP configuration. Cache only allowlisted model
  descriptions, resolved IDs and effort capabilities; discard account fields. This does not read the user's
  conversation or settings. Do not equate no model turn with no native metadata network activity.
- Prefer exact alias rows. Unambiguous variant rows such as `opus[1m]` may describe alias `opus`; conflicting
  rows are excluded. `model_catalog_value`, `model_catalog_resolved_id` and `model_catalog_source` record
  descriptive provenance. The submitted alias does not guarantee that revision or context size.

Reuse model-purpose descriptions without a time expiry while available model identities are known.
New identities or missing descriptions trigger metadata refresh and official price refresh for the entire
available inventory. Keep inventory IDs even when a row cannot yet supply purpose text; do not offer an
undescribed candidate or infer its capabilities from the model name.

Price references:
- Candidates carry official standard API rates in USD per million tokens, with source and freshness.
  Match exact provider IDs; a Claude launch alias alone cannot establish a price. Unknown prices do not
  exclude candidates and must not become zero, estimated rates, or a different model's price.
- Keep input, output, cache reads, cache writes and short/long context bands distinct. Claude cache writes
  have separate five-minute and one-hour rates. These are API references, not subscription billing,
  actual child spend or realized savings.
- Refresh all prices for the current client's catalog in the background after 24 hours and when new
  model metadata is needed. On failure, retain prior rates as stale. Purpose reuse and price freshness
  are separate: published prices can change while model IDs remain the same.

The shared Jev context also includes visible-task token estimates and each model's estimated uncached
input cost. The default is `ceil(UTF-8 bytes / 4)` over filtered task/description text, marked approximate.
It is not a verified local GPT-6/Claude tokenizer or a count of the full child prompt: host instructions,
tools, prior context and future output are unavailable. Keep standard and long-context cost alternatives,
unknown prices and stale-price provenance explicit. Do not replace Jev's actual usage with this estimate
or make an extra API/model call to compute it.

Any missing config/key, invalid answer, network error or timeout leaves the original launch unchanged.
Shadow mode records Jev's choice without rewriting. Routing errors do not block the user's subagent.

Sources: [Claude frontmatter](https://code.claude.com/docs/en/sub-agents#supported-frontmatter-fields),
[model precedence](https://code.claude.com/docs/en/sub-agents#choose-a-model),
[effort support and overrides](https://code.claude.com/docs/en/model-config#adjust-effort-level),
[hook updatedInput](https://code.claude.com/docs/en/hooks#pretooluse-decision-control).
Plugin effort frontmatter is supported from Claude Code 2.1.78; the current model precedence is from
2.1.251. The native Agent contract and definition-based effort were inspected on 2.1.280.

## Prelaunch notice

A successful choice emits a top-level `systemMessage` with a bounded, redacted task label and the chosen
model/effort, reason `choice`. It is emitted before the launch tool runs. Shadow notices say recommendation
and launch arguments unchanged. Skips and failed requests remain silent; their reason is recorded.

These are submitted launch parameters, not observed runtime execution. Do not describe a choice as a
verified child model or completed launch. No parent model/effort is inferred. `additionalContext` is not
used as a user-facing notice. Rendering varies by client: Codex may use a UI/event-stream warning.

## Installed updates and running versions

From 0.4.8, synchronous `SessionStart` and `UserPromptSubmit` handlers can emit an update notice through
`systemMessage`, without `additionalContext`, a model request or an automatic install. They compare the
executing plugin copy with native installed metadata and deduplicate by session/installed version. They
cannot notify from an older session that never loaded the checker. Native metadata errors or ambiguous
installations do not prove an update and produce no notice. Checks are cached for 60 seconds; only stable
`major.minor.patch` versions are compared. Bounded private state stores hashes, versions and timestamps,
not raw session IDs, paths or prompt text.

For Claude, use the documented `/reload-plugins` in the active session; it may defer to preserve a warm
prompt cache. Never force `/reload-plugins --force` without the user's choice: an uncached conversation
request can cost money outside the router's Jev accounting. For Codex, a new session is the documented
activation path; review/trust changed hooks through `/hooks` when needed. Do not infer loaded hook state
from an updated skill catalog or installed manifest. No automatic updater timer is installed.
Sources: [Claude plugins](https://code.claude.com/docs/en/discover-plugins),
[Claude hook output](https://code.claude.com/docs/en/hooks#json-output),
[OpenAI Docs plugins](https://learn.chatgpt.com/docs/plugins),
[OpenAI Docs hooks](https://learn.chatgpt.com/docs/hooks).

When reporting versions, distinguish the plugin's `plugin_version`, the executing host client's
`agent_version`, and the selected model. Use runtime evidence, not an arbitrary `claude`/`codex` on PATH.
The retained `claude-session` command initializes client versions only; it does not track session models.
The actual native client is probed once during `SessionStart` (Linux, two-second bound); ordinary hooks
read only its private exact-session cache, with no version subprocess or `/proc` scan. Unavailable/expired
client metadata remains unknown. Last-seen data records actual hook observations, not worker
heartbeats or an inventory of all hosts. Historical/mixed versions and missing reporters do not prove
that an update failed or that every session is current.

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

## Setup (agent performs these steps)

1. Create the private config only for a new installation; edit an existing config without replacing it:
   ```bash
   install -d -m 700 ~/.config/subagent-model-router
   install -m 600 "<plugin root>/config.example.toml" ~/.config/subagent-model-router/config.toml
   ```
2. Key — ask for the provider and an existing private key-file path, never for the key value in chat.
   Configure `key_file` to that path, or copy the file only when authorized, preserving owner-only permissions.
   Never display its contents. For an existing configured installation, reuse the configured file.
   Keys can be obtained at console.typesafe.ai/keys or openrouter.ai/settings/keys. Set
   `provider = "openrouter"` for OpenRouter. Run `check` yourself; no live Jev request is needed.
3. Codex only: a hook runs there only once it is trusted. Run `subagent-model-router codex-trust` (add
   `--codex <path>` when `codex` is not on `PATH`, e.g. the binary of the VS Code extension; `--dry-run` shows
   what would be trusted). The manual fallback is the `/hooks` screen in Codex. Then run `check` once to fill
   both native model catalog caches. Installing for another account with `sudo -u`, run `codex plugin …` from that
   account's home directory: Codex reads `.codex/config.toml` of the current directory as a project layer.

## Commands

- `check [--live]` — config path, mode, provider, endpoint, Jev model, allowed candidates for both products,
  binaries and their native model catalogs (up to 30 s per refresh; this fills the caches the hook
  reads), whether the key exists with the right permissions (never its content). `--live` makes one small
  request to Jev.
- `preview [TEXT] [-d DESCRIPTION]` — exact filtered Jev state without network access; use only when asked.
- `explain --agent codex|claude [TEXT]` (or text on stdin, `-d DESCRIPTION`) — offer that client's
  candidates to Jev and show the direct choice. This makes a real provider request with the task text; use
  it within the user's requested diagnostic scope. It does not write the journal.
- `stats [--days N] [--project NAME] [--user NAME] [--agent codex|claude] [--terminal] [--browser|--open] [--json]` — queries the configured storage. VM mode returns bounded
  summary/graphs; local mode retains the journal summary. `--source local` explicitly reads old history.
- `telemetry-status` — local delivery health without a network call.
- `codex-trust [--codex PATH] [--dry-run]` — mark this plugin's hooks trusted in Codex through `codex
  app-server`, the same way `/hooks` does. Only hooks Codex lists for the plugin `subagent-model-router` whose
  command is exactly `…/bin/subagent-model-router hook`, `… telemetry-kick`, `… claude-session` or `… update-notice` count;
  all other hooks are never touched. `claude-session` initializes version metadata only.

## Config

`~/.config/subagent-model-router/config.toml` (directory 0700, file 0600; `SUBAGENT_MODEL_ROUTER_CONFIG`
overrides the path). Every key and default is in `config.example.toml`. An unknown key or a bad value is a
config error (`error:config`) and the hook stays silent — as it does when the file or its directory belongs to
someone else or is writable by group or others; `check` names the problem.

Known legacy tier tables, thresholds and transcript-observation fields are accepted but ignored;
`check` reports migration warnings. Remove these fields when updating an existing config without changing
provider, key-file, exclusions or telemetry settings. Unknown keys still fail validation.
`timeout_seconds` (3 s, at most 8 s) bounds the whole request including one retry on 429/5xx.

## Monitoring

For VictoriaMetrics setup, delivery guarantees, Grafana import and report commands, read
[references/monitoring.md](references/monitoring.md). Collection and rendering are Python code shared by both
hosts: never schedule an agent, poll with an LLM, read raw history or call Jev to collect monitoring data. For money, separate reported router spend from
whole-account/key usage; show cost coverage, separate input/output token coverage, and balance age/probe status.
Historical classifier and local-lookup metrics are preserved but removed from the main dashboard.
They do not describe current routing, and missing observations must not be presented as zero.
When asked for statistics, run the resolved executable with `stats --days N --terminal` (default: 7 days).
Use `--project`, `--user`, `--agent codex|claude` when requested. Local journal rows lacking a requested cohort do not match; do not infer it from paths.
Copy the resulting dashboard into the **final response**, preserving the tables/bars/trend gaps. Tool output
alone is not delivery: the user must see the statistics in the agent's answer. Add only a short interpretation;
do not recompute charts in the LLM or invent unavailable values. State source, window and scope.

For a browser/HTML request, also use `--browser`: this returns a random short-lived loopback URL serving HTML
from memory. Open that exact URL in an available in-app browser using its documented tool/skill. Do not
inspect existing tabs, sessions or history. If no suitable in-app browser is available, use `--open` instead
of `--browser` to ask the local default browser to open the page. Prefer a browser on the user's machine;
loopback on an SSH/container host is not the user's loopback. If no reachable browser exists or opening fails,
keep the complete terminal dashboard in the answer and explain the browser limitation briefly. Never ask the
user to find/open a report file or claim that a browser rendered the page merely because an opener returned.

Do not create persistent HTML as the default. The browser helper uses no report file and expires after ten
minutes. If the user explicitly requests an exported artifact, use `mkstemp`/`NamedTemporaryFile` in a private
random directory under the platform's authorized temporary root (this workspace: /var/tmp), with a random
`.html` filename and mode0600. A fixed name is allowed only when the user explicitly supplies the destination.
Detailed command/API choices belong to the agent; user-facing instructions are ordinary chat requests.

## Journal (local backend)

`~/.local/state/subagent-model-router/decisions.jsonl` (`SUBAGENT_MODEL_ROUTER_LOG` overrides): one JSON line
per subagent call with client/task metadata, provider/request metadata, selected `model` and `effort`,
`reason`, `mode`, and observed client/plugin versions. The task text and key are never written.
A valid Jev decision has `reason="choice"`; `model` and `effort` are the chosen candidate, including in
shadow mode. Native no-effort candidates have null effort. Submitted parameters are not runtime proof. Claude effort passed through
an agent definition is marked `effort_source="agent_definition"` in telemetry.

Skip/error reasons include explicit selection, forks, unsupported type, exclusions, disabled routing,
missing key/catalog, native environment overrides and `error:<kind>`. Use the recorded reason rather than
inventing a fallback choice. Legacy journal entries are not rewritten into the new schema.

## How to answer requests

- "Which models did subagents get" — `stats` (`--days N` if asked), using the configured backend.
  Read individual journal entries only in local mode when details are needed; VM stores aggregates.
- "Why this model" / "what would it pick" — `explain --agent codex|claude` with the task text for the requested client.
- "Turn it off" / "turn it on" — `enabled = false` / `true` in the config. Removing the plugin (`/plugin` in
  Claude Code, `codex plugin remove`) only on a direct request.
- "Observe only" — `mode = "shadow"`; back with `mode = "active"`.
- "Set up the key" — perform Setup using the authorized file, then `check`; `check --live` only when asked to test the
  connection.
- "Do not send tasks from project X" — add its directory to `exclude`: that directory and everything inside it
  are excluded, but not a neighbour whose name merely starts the same (`~/work/x` does not cover `~/work/x.com`).
- "Trust the hook in Codex" — `codex-trust`, with `--dry-run` first when unsure what it will touch.
