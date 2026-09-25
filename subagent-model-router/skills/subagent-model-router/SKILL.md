---
name: subagent-model-router
description: Jev (TypeSafe AI) picks the model for every subagent from the text of its task, in Claude Code and in Codex, while the main session keeps the model chosen by hand. Use when the user asks which models subagents were given, why a task got a particular model, to turn model routing on or off, to switch it to observe-only (shadow) mode, to set up or check the TypeSafe or OpenRouter key, to exclude directories, to trust the hook in Codex, or to configure VictoriaMetrics monitoring and show router statistics/dashboards. Also triggers on «какие модели выбирались субагентам», «почему субагенту такая модель», «включи выбор модели», «выключи выбор модели», «режим наблюдения», «настрой ключ», «доверь хук в Codex».
---

# Subagent Model Router

A `PreToolUse` hook on the tool that starts a subagent — `Agent` in Claude Code, `spawn_agent` in Codex.
Before the subagent starts, the hook asks Jev three questions about its task and sets the subagent's model
(in Codex also its reasoning effort). The main session is never touched.

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

## What it changes and what it leaves alone

Claude Code:
- Only `Agent` calls without an explicit `model`, and only of the types in `[claude] route_types`
  (default `general-purpose`; a call without `subagent_type` counts as `general-purpose`). `Explore`, `Plan`,
  custom agents and forks are left alone.
- `light` → `haiku`, `standard` → `sonnet`, `heavy` → `inherit` (the call is left alone and the subagent runs
  on the session model). Effort is not chosen: the `Agent` call has no effort parameter.
- No `permissionDecision`: permissions work as before. `updatedInput` carries every original field plus `model`.

Codex:
- `spawn_agent` (multi-agent v1) and `collaborationspawn_agent` (v2).
- Left alone: a call that already sets `model` or `reasoning_effort`; a full fork — v2 without `fork_turns` or
  with anything but `"none"` (the default is `all`), v1 with `fork_context: true`; a role (`agent_type`) not
  in `[codex] route_agent_types` (default: no role, `default`, `worker`) — reason `type`.
- `light` → `gpt-5.6-luna` / `low`, `standard` → `gpt-5.6-terra` / `medium`, `heavy` → `inherit`.
- Model and effort are checked against the catalog from `codex debug models` of the codex binary that runs the
  session — the `codex` process that started the hook, then `codex_bin`, then `codex` on `PATH` (absolute
  entries only). A model the catalog lacks is not set; an effort the resulting model does not support is not
  set; no catalog, nothing set.
- The hook never waits for that catalog: it reads it from its cache (per binary path and modification time;
  fresh for 24 hours, used up to 7 days old) and starts a background refresh when the cache is missing or older
  than 24 hours — one at a time, at most 30 s. With no usable cache nothing is set and the journal says
  `no_catalog;refreshing`. `check` fetches the catalog synchronously (up to 30 s) and fills the cache.
- The output is `permissionDecision: "allow"` with `updatedInput` — Codex rewrites arguments only that way.
- A routed role whose file sets its own model overrides the choice.

Both: any failure — no config or key, network, timeout, an odd answer — means exit 0 without output. The
subagent starts as usual and the reason goes to the journal.

## Prelaunch notice

After each successful Jev decision, the hook emits a top-level `systemMessage` for the user in both Claude
Code and Codex: the subagent label, selected model, Codex reasoning effort and decision reason. This is emitted
by synchronous `PreToolUse`, before the launch tool runs. `additionalContext` is not a user-facing notice.
Inherited models show the session model supplied by the host plus `(unchanged)`; if omitted, `unknown
(unchanged)` is used. No transcript or private client config is read to guess it. Effort uses effective launch arguments or the host-provided level (Claude effort.level); absent evidence
is shown as unknown (unchanged), never guessed from defaults; catalog-rejected choices are not shown as selected. Shadow
mode explicitly labels its recommendation and says launch arguments are unchanged. No extra request is made.
Skipped calls and failed Jev requests remain silent. Labels are redacted, stripped of control characters and
bounded; task text is never included. The notice is a selection, not proof of a successful launch or a
role's final model. Client rendering varies: Codex uses a UI/event-stream warning; do not promise a separate
chat message or identical presentation in every client. Tests verify hook output, not client rendering.

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

## Setup (agent performs these steps)

1. Config (the plugin reads nothing until it exists):
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
   the model catalog cache. Installing for another account with `sudo -u`, run `codex plugin …` from that
   account's home directory: Codex reads `.codex/config.toml` of the current directory as a project layer.

## Commands

- `check [--live]` — config path, mode, provider, endpoint, Jev model, models for both products, the codex
  binary and model catalog (fetched now, up to 30 s, with the time it took; this fills the cache the hook
  reads), whether the key exists with the right permissions (never its content). `--live` makes one small
  request to Jev.
- `preview [TEXT] [-d DESCRIPTION]` — exact filtered Jev state without network access; use only when asked.
- `explain [TEXT]` (or the text on stdin, `-d DESCRIPTION`) — ask Jev about a task and show the answers, the
  threshold bands and the result for Claude Code and for Codex. It is a real request: warn the user that the
  text goes to TypeSafe or OpenRouter. It does not write the journal.
- `stats [--days N] [--project NAME] [--user NAME] [--agent codex|claude] [--terminal] [--browser|--open] [--json]` — queries the configured storage. VM mode returns bounded
  summary/graphs; local mode retains the journal summary. `--source local` explicitly reads old history.
- `telemetry-status` — local delivery health without a network call.
- `codex-trust [--codex PATH] [--dry-run]` — mark this plugin's hooks trusted in Codex through `codex
  app-server`, the same way `/hooks` does. Only hooks Codex lists for the plugin `subagent-model-router` whose
  command is exactly `…/bin/subagent-model-router hook` count; all other hooks are never touched.

## Config

`~/.config/subagent-model-router/config.toml` (directory 0700, file 0600; `SUBAGENT_MODEL_ROUTER_CONFIG`
overrides the path). Every key and default is in `config.example.toml`. An unknown key or a bad value is a
config error (`error:config`) and the hook stays silent — as it does when the file or its directory belongs to
someone else or is writable by group or others; `check` names the problem.

Rules: `risky ≥ risky_max` or `review ≥ review_max` → heavy; otherwise `P(light) ≥ light_min` → light;
otherwise `P(light) + P(standard) ≥ standard_min` and `P(heavy) < heavy_max` → standard; otherwise heavy.
`timeout_seconds` (3 s, at most 8 s) is the budget for the whole request including one retry on 429/5xx.

## Monitoring

For VictoriaMetrics setup, delivery guarantees, Grafana import and report commands, read
[references/monitoring.md](references/monitoring.md). Collection and rendering are Python code shared by both
hosts: never schedule an agent, poll with an LLM, read raw history or call Jev to collect monitoring data. For money, separate reported router spend from
whole-account/key usage; show cost coverage and balance age/probe status. Never turn missing cost into zero.
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
per subagent call with `ts`, `agent` (`claude`/`codex`), `session_id`, `cwd`, `subagent_type`, `description`,
`state_sha256`, `provider`, `jev_model`, `request_id`, `latency_ms`, `answers`, `tier`, `model`, `effort`,
`session_model`, `reason`, `mode`. The task text is never written, the key never.

Reasons: `explicit`, `fork`, `type`, `excluded`, `off`, `no_key`, `error:<kind>`; Jev decisions are
`rule:light|standard|heavy|risky|review`. In Codex a decision may carry notes after `;`: `no_codex` (no codex
binary found), `no_catalog` (followed by `;refreshing` while a background refresh runs), `model_not_in_catalog`,
`effort_not_supported`; `model`/`effort` are then `null`.

## How to answer requests

- "Which models did subagents get" — `stats` (`--days N` if asked), using the configured backend.
  Read individual journal entries only in local mode when details are needed; VM stores aggregates.
- "Why this model" / "what would it pick" — `explain` with the task text, after warning where the text goes.
- "Turn it off" / "turn it on" — `enabled = false` / `true` in the config. Removing the plugin (`/plugin` in
  Claude Code, `codex plugin remove`) only on a direct request.
- "Observe only" — `mode = "shadow"`; back with `mode = "active"`.
- "Set up the key" — perform Setup using the authorized file, then `check`; `check --live` only when asked to test the
  connection.
- "Do not send tasks from project X" — add its directory to `exclude`: that directory and everything inside it
  are excluded, but not a neighbour whose name merely starts the same (`~/work/x` does not cover `~/work/x.com`).
- "Trust the hook in Codex" — `codex-trust`, with `--dry-run` first when unsure what it will touch.
