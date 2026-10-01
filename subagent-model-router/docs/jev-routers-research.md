# Other Jev-based routers: what to borrow (research backlog)

Status: research notes, nothing here is implemented. Written 2026-10-02 against
subagent-model-router 0.6.1 (`9e785ce`).

Two unrelated open-source projects also put Jev (TypeSafe's decision model) in front of agents.

| | [JevRouter](#jevrouter) | [jev-router](#jev-router) | subagent-model-router |
|---|---|---|---|
| What it routes | tool/skill/MCP/subagent/model choice, on the agent's request | main-session model per user turn | subagent model + effort per launch |
| Mechanism | Skill + CLAUDE.md/AGENTS.md rule, CLI/SDK/MCP | loopback proxy that rewrites `model` in API requests | PreToolUse hook on `Agent` / `spawn_agent` |
| Reasoning effort | no | strips/clamps only | chosen |
| Native catalogs / prices | no / no | `/v1/models` ids / no | yes / yes |
| Observability | JSON receipts, local dashboard | per-session status file | journal, VictoriaMetrics, Grafana, in-chat stats |
| Eval | tool-sequence benchmark (scripts not in repo) | RouterBench + agentic eval, both negative | tier and factor-policy evals; none for the direct Choice |
| State | v0.1.0, 2 weeks old, one maintainer | 0.3.0, silent since 2026-09-19, broken on current Claude Code | — |

Verdict: neither replaces our hook. The backlog below collects what is worth researching from both.

Line references use fixed commits:
- `JR:` = [BillionsBobby/JevRouter@e11084c](https://github.com/BillionsBobby/JevRouter/tree/e11084c808e1902d11230e7a7937e5008fec7f02)
  (`https://github.com/BillionsBobby/JevRouter/blob/e11084c808e1902d11230e7a7937e5008fec7f02/`)
- `GR:` = [gargpratyush/jev-router@38da6b8](https://github.com/gargpratyush/jev-router/tree/38da6b84ea01241bfc41fbddc0928d0f40a703f0), `main`
  (`https://github.com/gargpratyush/jev-router/blob/38da6b84ea01241bfc41fbddc0928d0f40a703f0/`)
- `GB:` = the same repo's unmerged `benchmarking` branch at `c08aee1`
  (`https://github.com/gargpratyush/jev-router/blob/c08aee16595bcd510acbd134465acebb361c7085/`)

## JevRouter

**What it is:** a TypeScript library and CLI (MIT, 88/88 offline tests pass) that asks Jev one
Choice question: "which capability handles this?". The candidates are tools, skills, MCP servers,
subagents and models, all supplied by the host.

**How the agent uses it:** through a Skill plus a block in `CLAUDE.md`/`AGENTS.md`, so the agent
has to decide to call it. Its docs say it is "not a tool interception layer"
(`JR:docs/agent-integration.md#L63`) and that it does not switch the host model or spawn agents
(`JR:skills/jevrouter/SKILL.md#L31`).

**What it lacks:** a hook, launch rewriting, reasoning effort, native catalogs, price-aware
selection (it takes the highest-probability safe candidate), metrics export, and a
model-routing eval. Adopting it would mean rebuilding all of that on top, and it would replace
only our ~150-line Jev client.

**Intended use:** tool selection. Its README benchmark predicts the first 5 tool calls on
Toolathlon tasks: Jev scores 38–44% position hits against 24% for DeepSeek V4.1 Flash, at about
1/7 of the cost. It does not measure model or effort choice.

**Already covered on our side:**

| JevRouter | Ours |
|---|---|
| HTTPS-or-loopback endpoint check (`JR:src/provider.ts#L77-L94`) | `_check_endpoint`, `bin/subagent-model-router:169-180` |
| Choice answer validation (`JR:src/provider.ts#L290-L309`, `JR:src/router.ts#L370-L376`) | `parse_response`, `bin/subagent-model-router:428-479`; stricter (see below) |
| Raw answer kept | journal `answers` with probabilities and confidence |
| State hash | `state_sha256` in the journal record |
| Several questions in one request (`JR:src/provider.ts#L20-L45`) | the factor policy sends 8 Score/Noul questions next to the Choice (`lib/router_factors.py`) |

Our answer validation is stricter than JevRouter's:
- probabilities must cover exactly the offered options;
- they must sum to 1 ± 0.02;
- the choice must be a max-probability option;
- unexpected answer keys are rejected.

## jev-router

**What it is:** `jev-claude` and `jev-codex` (npm 0.3.0, MIT, JavaScript, ~1.5k LOC, 65/65
tests pass). They launch the real CLI behind a loopback proxy and offer it a sentinel model
`jev-router`:
- Claude: via `ANTHROPIC_BASE_URL` and `ANTHROPIC_CUSTOM_MODEL_OPTION`;
- Codex: via a custom `model_providers.jev`.

For requests on the sentinel, the proxy detects a fresh user turn, asks Jev, and rewrites
`model` in the request body. Auth, sessions, tools and permissions stay native; there are no
hooks and no plugin.

**Scope:** the main conversation's model per user turn. It does not choose reasoning effort: it
strips thinking/effort for Haiku and clamps Codex effort. Jev gets no prices.

**When Jev is called:**
- One call per request that passes `newTurnPrompt` (`GR:src/proxy.mjs#L55-L72`). The request
  must have tools, end with a `role:user` message without a `tool_result`, and keep non-empty text
  after stripping `<system-reminder>`. Codex uses the same rules
  (`GR:src/codex-proxy.mjs#L84-L102`).
- Tool-loop continuations reuse the turn's pinned model (`GR:src/proxy.mjs#L260-L263`).
- Auxiliary calls without tools (titles, compaction) are never routed.
- Short replies such as "yes, continue" or "да" trigger a full Jev call: `main` has no
  continuation heuristic.
- After `--resume` the in-memory state is empty, so the next prompt is judged against the
  default `opus` (`GR:src/proxy.mjs#L216`).
- Each call blocks the request for up to 3 s: 1.5 s × 2 attempts (`GR:src/config.mjs#L64-L66`).

**What Jev sees:**
- Only the latest user text, the current model, a `JSON.length/4` context-token estimate, and
  the model ids (`GR:src/router.mjs#L37-L44`). No history, system prompt or tool results.
- Three 10-level Score questions (task complexity, reasoning, tool complexity) plus one Choice
  over exact model ids.
- The policy provides the stickiness Jev lacks (`GR:src/policy.mjs#L47-L58`):
  - keep the current model on any Jev failure;
  - below confidence 0.3, never downgrade and cap upgrades at sonnet;
  - never downgrade past 20k context tokens.

  In practice a short follow-up can only keep or raise the tier.

**Subagents:**
- **Claude:** subagents without a model inherit the sentinel. Each gets one Jev call on its first
  message, with its own task text, starting from `opus`. The main turn's decision does not
  propagate to them.
- **Codex:** the same, keyed by `prompt_cache_key`. All decisions overwrite one per-process
  status file.

**Their own evidence is negative** (`GB:bench/agentic/RESULTS.md`):
- **Agentic eval:** 87 tasks, $59, position-swapped Opus judge. Jev AUC is **0.570**
  [0.429, 0.693], below a free prompt-length baseline at **0.613**.
- **RouterBench:** 0.591, against 0.597 for random routing at the same escalation rate.
- **Downgrades:** Jev proposed Haiku 31 times and the shipped policy took it **0** times.
- **Cache cost:** a Claude Code turn's first request is at least ~37k tokens. A Haiku cache write
  costs 6× a Sonnet cache read, so a downgrade needs ~11 turns to pay back. Sessions average 4–6.
- **Savings ceiling:** a perfect oracle saves only 4–8%.

So routing the main session on the last message alone is not a cost tool. Any value would come
from upgrades (quality).

**State (2026-10-02):**
- **Activity:** 48 commits in 3 days (2026-09-17..19), one maintainer, silent since then;
  22 open issues and 13 open PRs.
- **Broken on current Claude Code:**
  - A trailing `role:system` message makes `newTurnPrompt` return null. Jev is never called and
    the session silently stays on Opus (#58, #48; fix in PR #36).
  - The context guard fires on turn 1 because of `CLAUDE.md` and hook output (#59).
- **Other defects:**
  - Background calls land on opus.
  - The sentinel costs the 1M context window (#35).
  - Override regexes have false positives ("fast paths" → haiku).
  - A concrete-model request wipes the explain history.
  - The project `.env` is loaded into the environment the CLI inherits.
- **Fragile protocol:** it depends on undocumented wire shapes (`metadata.user_id`, the role of
  the last message, Codex `additional_tools`/`prompt_cache_key`) and fabricates SSE commentary
  events.

**Coexistence with our plugin:** it works mechanically, because when our hook sets `model` the
proxy passes the request through (`GR:src/proxy.mjs#L205-L211`). Without patches, three
conflicts remain:
- every subagent we route flips the main session to "manual" and resets its explain history;
- when our hook fails open, jev-router routes the subagent with its own policy;
- one launch can cost two Jev calls.

Patching a fork: about 1 day.

**Main-turn routing for us:** hooks cannot set the main model or effort. `UserPromptSubmit` only
adds context, and `PreModelSwitch` only allows or blocks a switch already requested. A proxy is
the only route. Claude Code ≥ 2.1.273 has `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, which sends:
- `x-claude-code-request-class` (main/subagent/auxiliary/compaction);
- `x-claude-code-agent-id`;
- `x-claude-code-prompt-id`.

These would replace body sniffing.

Rough cost: a Claude MVP in stdlib Python takes 1–2 weeks, Codex another week, plus maintenance
against undocumented formats. Treat it as a separate experiment, gated on an eval showing
upgrades improve quality.

## Research backlog

Ordered by expected value per effort.

### 1. Eval for the direct Choice, with jev-router's methodology

**Gap:** our largest one. The direct Choice (0.5+) has no eval:
- `eval/run.py` covers the pre-0.5 tier router;
- `eval/factors_run.py` covers only the factor policy.

Items 3–6 depend on this eval.

**What to adopt** (`GB:bench/agentic/README.md`, `GB:bench/agentic/RESULTS.md`):
- label "does a stronger tier change the outcome" rather than "how hard is the task";
- compare against random routing at the same escalation rate, and against a prompt-length
  baseline;
- use a judge that sees answer pairs in both orders;
- verify the model that actually served each request.

**Cost:** 3–5 days.

### 2. Provenance hashes for candidates and policy

**Their approach:** JevRouter records `candidate_snapshot_hash = sha256(candidates)` and
`policy_hash = sha256(policy)` (`JR:src/router.ts#L310-L322`).

**Our gap:** we record `state_sha256`, but not which option set and which instruction/policy text
produced a choice. Decisions from before and after a catalog refresh, a price change or a prompt
edit look the same in stats and evals.

**What to do:**
- hash the sorted options (model, effort, purpose, price), and separately the instruction text
  plus the `[policy]` config;
- write both hashes to the journal, and a short prefix as a VictoriaMetrics label;
- check label cardinality.

**Cost:** about half a day.

### 3. Strip harness noise from the text sent to Jev

**Their approach:** jev-router strips `<system-reminder>`, `<environment_context>` and
`<current_datetime>` (`GR:src/proxy.mjs#L71`, `GR:src/codex-proxy.mjs#L73-L78`). Its author
reports that reminders blunt Jev's confidence.

**Ours:** we mask credentials but otherwise send the task text as is.

**What to do:**
- measure how often subagent prompts in our journal contain such blocks;
- A/B test on eval cases.

**Cost:** about half a day.

### 4. Confidence gate on the direct Choice

**Their approach:**
- JevRouter returns `no_decision` below `min_confidence` 0.55 (`JR:src/router.ts#L385-L402`,
  `JR:src/manifest.ts#L9-L18`);
- jev-router never downgrades and caps upgrades below 0.3 (`GR:src/policy.mjs#L51-L55`).

**Ours:** we store the Choice confidence but always apply the choice. Only the factor policy uses
confidence thresholds (`lib/router_factors.py:70,159-176`).

**What to research:**
- the confidence distribution, from the journal or VictoriaMetrics;
- what a low-confidence answer should do:
  - (a) leave the launch unchanged;
  - (b) take the factor-policy pick;
  - (c) move to the next more capable option;
- how often each option would fire.

**Caveat:** gate on the probability of the option we actually apply. JevRouter checks
confidence in Jev's own pick even after substituting another candidate
(`JR:src/router.ts#L396`).

**Cost:** small to implement; the threshold needs data.

### 5. Prompt-cache switch cost in the price model

**Their approach:** `GB:src/cache.mjs` and `GB:src/pricing.mjs` model cache writes and reads per
tier.

**Ours:** we price only uncached input and output.

**Open question:** subagents start their own conversation. How much prefix (system prompt, tool
schemas, CLAUDE.md) is cache-shared with the parent, and does a different model lose it? Measure
from usage fields before modelling.

**Cost:** 2–3 days.

### 6. Option-set size: two stages or split questions

Our options are every (model, effort) pair: 4 Claude aliases × up to 5 efforts, and Codex grows
with each release. A long criteria list costs input tokens and may dilute Jev's distribution.

**Variant A: two stages.** JevRouter does this above 32 candidates: a coarse Choice, keep the top
8, then a final Choice (`JR:src/router.ts#L336-L365`).
- Latency: two calls must fit our 3 s default / 8 s max budget.
- JevRouter merges the two stages' probabilities into one ranking (`JR:src/router.ts#L359`).
  Keep them separate.

**Variant B: split questions.** Ask a Choice over models plus a Score for effort, in one
request. This idea is ours, built on multi-question support.
- It cuts the candidates from M×E to M.
- Risk: model and effort interact.
- Effort must map to the nearest supported level; `lib/router_factors.py:select` already does
  this.

**What to do:**
- count current option totals per agent;
- compare the current pair Choice, variant A, variant B and the factor policy on the item 1
  eval.

**Cost:** 1–2 days of eval runs per variant.

### 7. Smaller ideas

- **Explicit model requests in the task text,** such as "use opus" (`GR:src/policy.mjs#L4-L7`,
  `GR:src/config.mjs#L87-L98`). Theirs is English-only with false positives. Prefer an anchored,
  language-aware rule or a Noul question. About half a day.
- **Last N exact Jev requests/responses per session** for an explain command
  (`GR:src/status.mjs#L40-L44`). Our journal stores answers but not the request body. About half
  a day.
- **Catalog fields such as `created_at` and `max_input_tokens`** in the Choice criteria
  (`GR:src/proxy.mjs#L101-L116`). Hours.
- **A record of router overrides,** if we ever filter options after Jev answers instead of
  before. JevRouter's `fallback.type/reason` is a good template (`JR:src/router.ts#L498-L517`).
- **A decision cache:** probably skip. JevRouter keeps it off by default
  (`JR:src/runtime.ts#L30-L31`), and our tasks rarely repeat verbatim.

## Not to copy

- **Long fixed timeouts:** JevRouter uses 15–20 s with no retry (`JR:src/provider.ts#L105,L149`).
  Ours is one 3 s deadline (8 s max) with one retry on 429/5xx that must fit it.
- **Unauthenticated loopback endpoints:** JevRouter `serve` (`JR:src/cli.ts#L172-L183`), and the
  jev-router proxy.
- **Leaking secrets to child processes:**
  - JevRouter starts MCP servers with the full `process.env`, Jev keys included
    (`JR:src/mcp.ts#L52-L53`);
  - jev-router loads the project `.env` into the environment the agent CLI inherits.
- **Plaintext prompts in decision records by default.** We mask credentials and keep the journal
  at mode 0600.
- **Relying on CLAUDE.md/AGENTS.md for the agent to choose to route:** the opposite of our hook
  design.
- **Body-sniffing turn detection on undocumented wire formats,** and defaulting to the most
  expensive tier when state is missing or Jev fails.
- **Silent writes outside the project:** rewriting `~/.claude/settings.json` on exit, or
  installing skills into `~/.agents`.

## Our own gaps found during this comparison

- **A. No eval for the direct Choice.** This is backlog item 1.
- **B. `bin/subagent-model-router` is 2,290 lines.** It mixes config, the Jev client, both
  catalogs, hook logic and commands. Moving the Jev client and option building into `lib/` would
  make items 2–6 easier to test.
- **C. Dead code:**
  - `lib/router_claude_model.py` and `lib/router_runtime.py` are used only by tests;
  - `TASK_FALLBACK_CHARS` is unused.
- **D. Stale docs and checks:**
  - `README.md` still opens with "Version 0.5.0";
  - `check --live` always probes Codex options.
