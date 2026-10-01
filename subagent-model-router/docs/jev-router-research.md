# jev-router: main-turn routing and what to borrow (research backlog)

Status: research notes, nothing here is implemented. Written 2026-10-02 against
subagent-model-router 0.6.1 (`9e785ce`). See also [jevrouter-research.md](jevrouter-research.md)
for the unrelated JevRouter project.

Source studied: [gargpratyush/jev-router](https://github.com/gargpratyush/jev-router) (npm
`jev-router` 0.3.0, MIT, JavaScript, ~1.5k LOC, 65/65 tests pass).
- `JR:` = `https://github.com/gargpratyush/jev-router/blob/38da6b84ea01241bfc41fbddc0928d0f40a703f0/` (`main`)
- `JB:` = `https://github.com/gargpratyush/jev-router/blob/c08aee16595bcd510acbd134465acebb361c7085/` (unmerged `benchmarking` branch)

## What it does

- **What it is:** wrappers `jev-claude` and `jev-codex` that launch the real CLI behind a
  loopback HTTP proxy. The CLI is pointed at the proxy and offered a sentinel model `jev-router`:
  - Claude: `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_MODEL_OPTION`;
  - Codex: a custom `model_providers.jev`.
- **What it does per request:** for each request on the sentinel, the proxy decides whether it is
  a fresh user turn, asks Jev, and rewrites the `model` field in the request body.
- **What stays native:** auth, sessions, tools and permissions. No hooks and no plugin.
- **Scope:** it routes the main conversation's model per user turn, which our plugin does not.
  It does not choose reasoning effort: it only strips thinking/effort for Haiku and clamps
  Codex effort to the catalog. Jev gets no prices.

### When Jev is called

- **Claude:** one call per request that passes `newTurnPrompt` (`JR:src/proxy.mjs#L55-L72`):
  - tools present;
  - last message is `role:user`;
  - no `tool_result` in it;
  - non-empty text after stripping `<system-reminder>`.
- **Codex:** the same idea (`JR:src/codex-proxy.mjs#L84-L102`).
- **What reuses the turn's pinned model:** tool-loop continuations (`JR:src/proxy.mjs#L260-L263`).
- **What is never routed:** auxiliary calls without tools (titles, compaction).
- **Short replies count:** "yes, continue" or "да" triggers a full Jev call. There is no
  continuation heuristic on `main`.
- **Resume:** after `--resume` the in-memory state is empty, so the next prompt is judged
  against the default `opus` (`JR:src/proxy.mjs#L216`).
- **Latency:** each call waits up to 3 s (1.5 s × 2 attempts) before the request is forwarded
  (`JR:src/config.mjs#L64-L66`).

### What Jev sees

- **State:** only the latest user text, the current model, an estimate of `JSON.length/4`
  context tokens, and the list of model ids (`JR:src/router.mjs#L37-L44`). No history, system
  prompt or tool results.
- **Questions:** three 10-level Scores (task complexity, reasoning, tool complexity) and one
  Choice over exact model ids.
- **Policy** (`JR:src/policy.mjs#L47-L58`), which supplies the stickiness Jev lacks:
  - keep the current model on any Jev failure;
  - below confidence 0.3, never downgrade and cap upgrades at sonnet;
  - never downgrade past 20k context tokens.

  In practice a short follow-up can only keep or raise the tier.

### Subagents

- **Claude:** subagents inherit the sentinel unless given a model, so they hit the proxy as a
  separate conversation key. Each gets exactly one Jev call on its first message, with its own
  task text, starting from `opus`. Internal steps reuse that pin.
- **No propagation:** the main turn's decision does not propagate to subagents.
- **Codex:** same pattern, keyed by `prompt_cache_key`. Every decision overwrites one
  per-process status file.

## Their own evidence is negative

Their own evidence (unmerged `benchmarking` branch, `JB:bench/agentic/RESULTS.md`):
- **Agentic eval:** 87 tasks, $59, position-swapped Opus judge. Jev AUC is **0.570**
  [0.429, 0.693], below a free prompt-length baseline at **0.613**.
- **RouterBench:** 0.591, against 0.597 for random routing at the same escalation rate.
- **Downgrades:** Jev proposed Haiku 31 times and the shipped policy took it **0** times.
- **Cache cost:** the first request of a Claude Code turn is at least ~37k tokens. Switching
  model rewrites the prompt cache: a Haiku cache write costs 6× a Sonnet cache read. A downgrade
  needs about 11 turns to pay back, while sessions average 4–6.
- **Savings ceiling:** a perfect oracle saves only 4–8%.

Conclusion: main-turn routing on the last message alone is not a cost tool. Any value would come
from upgrades (quality), not downgrades.

## State of the project (2026-10-02)

- **Activity:** 48 commits in 3 days (2026-09-17..19), one maintainer, last push 2026-09-19.
  22 open issues and 13 open PRs.
- **Broken on current Claude Code:** a trailing `role:system` message makes `newTurnPrompt`
  return null, so Jev is never called and the session silently stays on Opus (issues #58, #48;
  fix in PR #36). The context guard also fires on turn 1 because of `CLAUDE.md` and hook output
  (#59).
- **Other defects:**
  - Background calls (titles, summaries) land on opus.
  - The sentinel model costs the 1M context window (#35).
  - Override regexes have false positives ("fast paths" → haiku).
  - A concrete-model request wipes the explain history.
  - The project `.env` is loaded into the environment inherited by the CLI, so its secrets are
    visible to the model's Bash tool.
- **Fragile protocol:** routing relies on undocumented wire shapes such as `metadata.user_id`,
  last-message role, and Codex `additional_tools`/`prompt_cache_key`. It also fabricates SSE
  commentary events.

## Coexistence with our plugin

It works mechanically: when our hook sets `model`, the proxy passes the request through
(`JR:src/proxy.mjs#L205-L211`). Known conflicts without patches:
- every subagent we route flips the main session to "manual" and resets the explain history;
- when our hook fails open, jev-router routes the subagent with its own policy;
- a single launch can cost two Jev calls.

Estimated fork patches: about 1 day.

## Main-turn routing for us

- **Why not via hooks:** no hook output can set the main model or effort. `UserPromptSubmit` can
  only add context, and `PreModelSwitch` can only allow or block a switch already requested.
- **The only route is a proxy, as here.** Claude Code ≥ 2.1.273 has
  `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, which sends `x-claude-code-request-class`
  (main/subagent/auxiliary/compaction), `x-claude-code-agent-id` and `x-claude-code-prompt-id`.
  These would replace body sniffing.
- **Rough cost:** Claude MVP in stdlib Python, 1–2 weeks; Codex, +1 week; plus ongoing
  maintenance against undocumented formats.
- **Decision:** treat this as a separate experiment, gated on an eval showing that upgrades
  improve quality.

## Candidates to borrow

Ordered by expected value per effort.

### 1. Eval methodology

Sources: `JB:bench/agentic/README.md`, `JB:bench/agentic/RESULTS.md`.

**Gap:** this fills our largest gap, which is no eval for the direct Choice (0.5+). See gap A in
[jevrouter-research.md](jevrouter-research.md#our-own-gaps-found-during-this-comparison).

**Ideas to adopt:**
- label "does a stronger tier change the outcome" rather than "how hard is the task";
- compare against random routing at the same escalation rate and against a prompt-length
  baseline;
- use a judge that sees answer pairs in both orders;
- verify the model that actually served the request.

**Cost:** 3–5 days.

### 2. Strip harness noise from the text sent to Jev

**JR:** strips `<system-reminder>`, `<environment_context>` and `<current_datetime>`
(`JR:src/proxy.mjs#L71`, `JR:src/codex-proxy.mjs#L73-L78`). The author reports reminders blunt
Jev's confidence.

**Ours:** we mask credentials but send the task text as is.

**Research:**
- check how often subagent prompts contain such blocks in our journal;
- A/B test on eval cases.

**Cost:** about half a day.

### 3. Confidence-aware policy

**JR:** low confidence never downgrades and caps upgrades (`JR:src/policy.mjs#L51-L55`).

**Ours:** same idea as item 2 in jevrouter-research.md, so research them together. Gate on the
probability of the option we apply.

**Cost:** about half a day plus data analysis.

### 4. Prompt-cache switch cost in the price model

**JB:** `src/cache.mjs` and `src/pricing.mjs` model cache writes/reads per tier.

**Ours:** price only uncached input/output.

**Open question:** subagents start their own conversation, so how much prefix (system prompt,
tool schemas, CLAUDE.md) is cache-shared with the parent, and does a different model lose it?
Measure from usage fields before modelling.

**Cost:** 2–3 days.

### 5. Explicit model requests in the task text

**JR:** regex overrides such as "use opus" (`JR:src/policy.mjs#L4-L7`,
`JR:src/config.mjs#L87-L98`). Theirs has false positives.

**Ours:** consider an anchored, language-aware rule or a Noul question instead.

**Cost:** about half a day.

### 6. Smaller ideas

- **Per-session debug record:** keep the last N exact Jev requests/responses per session for an
  explain command (`JR:src/status.mjs#L40-L44`). Our journal stores answers but not the request
  body. About half a day.
- **Richer criteria:** add catalog fields such as `created_at` and `max_input_tokens` to the
  Choice criteria (`JR:src/proxy.mjs#L101-L116`). Hours.

## Not to copy

- Body-sniffing turn detection on undocumented wire formats.
- A default of the most expensive tier when state is missing or Jev fails.
- Loading the project `.env` into the environment inherited by the agent CLI.
- Rewriting `~/.claude/settings.json` on exit, or installing skills into `~/.agents` silently.
- English-only, unanchored override regexes.
