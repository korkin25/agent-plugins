---
name: subagent-model-router
description: Jev (TypeSafe AI) picks the model for every subagent from the text of its task, in Claude Code and in Codex, while the main session keeps the model chosen by hand. Use when the user asks which models subagents were given, why a task got a particular model, to turn model routing on or off, to switch it to observe-only (shadow) mode, to set up or check the TypeSafe or OpenRouter key, to exclude directories, to trust the hook in Codex, or to configure VictoriaMetrics monitoring and show router statistics/dashboards. Also triggers on «какие модели выбирались субагентам», «почему субагенту такая модель», «включи выбор модели», «выключи выбор модели», «режим наблюдения», «настрой ключ», «доверь хук в Codex».
---

# Subagent Model Router

A `PreToolUse` hook on the tool that starts a subagent — `Agent` in Claude Code, `spawn_agent` in Codex.
Before the subagent starts, the hook asks Jev three questions about its task and sets the subagent's model
(in Codex also its reasoning effort). The main session is never touched.

The command: in Claude Code the plugin's `bin/` is on `PATH`, so it is `subagent-model-router <command>`.
In Codex or a plain shell, call it by path: the plugin root is two directories above this `SKILL.md`, so
`<plugin root>/bin/subagent-model-router <command>`.

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
Inherited model/effort are reported as unchanged; catalog-rejected choices are not shown as selected. Shadow
mode explicitly labels its recommendation and says launch arguments are unchanged. No extra request is made.
Skipped calls and failed Jev requests remain silent. Labels are redacted, stripped of control characters and
bounded; task text is never included. The notice is a selection, not proof of a successful launch or a
role's final model. Client rendering varies: Codex uses a UI/event-stream warning; do not promise a separate
chat message or identical presentation in every client. Tests verify hook output, not client rendering.

## What leaves the machine

One request per subagent start, to TypeSafe (`provider = "typesafe"`) or OpenRouter (`"openrouter"`):
`state = {"description": …, "task": …}`. In Claude Code the description is the call's `description`; in Codex
it is `task_name` (or `agent_type`). `task` is the task lines that start with `TASK:` and `ROLE:`, or the first
1500 characters of the task when there are none. Common credential formats are masked with `[redacted]` first:
GitLab (`glpat-…`), GitHub (`ghp_…`, `gho_…`, `github_pat_…`), `sk-…`, Slack (`xox?-…`), AWS (`AKIA…`)
and Google (`AIza…`) keys, JWTs, `PRIVATE KEY` blocks, `Bearer` and `Authorization: Basic` credentials,
`user:password@` in URLs, `--password <value>`, and values after `password`, `passwd`, `token`, `secret`,
`api_key`/`api-key` (so `X-Api-Key:` too) with `:` or `=`.
Do not rely on it for anything else: a secret in any other form is sent as written. Nothing else is sent to Jev.
With the optional VictoriaMetrics backend, aggregate metrics also go to the user-configured VM endpoint;
task text and identifying journal fields are never included. See Monitoring below.

## Setup

1. Config (the plugin reads nothing until it exists):
   ```bash
   install -d -m 700 ~/.config/subagent-model-router
   install -m 600 "<plugin root>/config.example.toml" ~/.config/subagent-model-router/config.toml
   ```
2. Key — the user puts it in place personally. Never read or print the key, and never ask for it in the chat:
   ```bash
   ( umask 077; cat > ~/.config/subagent-model-router/key )   # paste the key, Enter, Ctrl-D
   ```
   TypeSafe keys: console.typesafe.ai/keys. OpenRouter keys: openrouter.ai/settings/keys, together with
   `provider = "openrouter"`. Then run `check`.
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
- `explain [TEXT]` (or the text on stdin, `-d DESCRIPTION`) — ask Jev about a task and show the answers, the
  threshold bands and the result for Claude Code and for Codex. It is a real request: warn the user that the
  text goes to TypeSafe or OpenRouter. It does not write the journal.
- `stats [--days N] [--project NAME] [--user NAME] [--json] [--html PATH]` — queries the configured storage. VM mode returns bounded
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
hosts: never schedule an agent, poll with an LLM, read raw history or call Jev to collect monitoring data.
When asked for statistics, run `stats --days N --json` (default VM window: 7 days); for a visual report add
`--html PATH` and return the file link with a short factual interpretation. Use the bundled report/dashboard
instead of recreating charts in the model. Distinguish unavailable/empty data from zero and selection share
from demonstrated token, money or quality savings. Report the queried time window and source.

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
- "Set up the key" — give the commands from Setup, then `check`; `check --live` only when asked to test the
  connection.
- "Do not send tasks from project X" — add its directory to `exclude`: that directory and everything inside it
  are excluded, but not a neighbour whose name merely starts the same (`~/work/x` does not cover `~/work/x.com`).
- "Trust the hook in Codex" — `codex-trust`, with `--dry-run` first when unsure what it will touch.
