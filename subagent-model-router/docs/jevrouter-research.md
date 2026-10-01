# JevRouter: what to borrow (research backlog)

Status: research notes, nothing here is implemented. Written 2026-10-02 against
subagent-model-router 0.6.1 (`9e785ce`). See also [jev-router-research.md](jev-router-research.md)
for the unrelated jev-router project (main-turn routing through a proxy).

Source studied: [BillionsBobby/JevRouter](https://github.com/BillionsBobby/JevRouter) at
[`e11084c`](https://github.com/BillionsBobby/JevRouter/tree/e11084c808e1902d11230e7a7937e5008fec7f02)
(v0.1.0, MIT, TypeScript, 88/88 offline tests pass). Line references below point at that commit;
`JR:` is short for `https://github.com/BillionsBobby/JevRouter/blob/e11084c808e1902d11230e7a7937e5008fec7f02/`.

## Verdict

JevRouter is not a replacement. It is a library/CLI that asks Jev one Choice question
("which capability handles this?") over candidates the host supplies: tools, skills, MCP
servers, subagents, models. It is used through a Skill and a block in `CLAUDE.md`/`AGENTS.md`,
so the agent has to decide to call it. Its own docs say it is "not a tool interception layer"
(`JR:docs/agent-integration.md#L63`) and that it does not switch the host model or spawn agents
(`JR:skills/jevrouter/SKILL.md#L31`).

It has none of: a PreToolUse hook, launch rewriting, reasoning effort, native Claude/Codex
catalogs, price-aware selection, metrics export, or a model-routing eval. Adopting it would mean
rebuilding all of those on top and would only replace our ~150-line Jev client.

The author's intended use is tool selection for agents. The README benchmark predicts the
first 5 tool calls on Toolathlon tasks (Jev 38–44% position hits vs DeepSeek V4.1 Flash 24%, at
about 1/7 of the cost). It does not measure model or effort choice.

## Already covered on our side

These looked borrowable at first. A check against our code shows we already have them:

| JevRouter | Ours |
|---|---|
| HTTPS-or-loopback endpoint check (`JR:src/provider.ts#L77-L94`) | `_check_endpoint`, `bin/subagent-model-router:169-180` |
| Choice answer validation (`JR:src/provider.ts#L290-L309`, `JR:src/router.ts#L370-L376`) | `parse_response`, `bin/subagent-model-router:428-479`. Ours is stricter: probabilities must cover exactly the offered options and sum to 1 ± 0.02, the choice must be a max-probability option, and unexpected answer keys are rejected. |
| Raw answer kept | journal `answers` with probabilities and confidence |
| State hash | `state_sha256` in the journal record |
| Multi-question request (`JR:src/provider.ts#L20-L45`) | the factor policy already sends 8 Score/Noul questions next to the Choice (`lib/router_factors.py`) |

## Candidates to research

Ordered by expected value per effort.

### 1. Provenance hashes for candidates and policy

**JevRouter:** each decision records `candidate_snapshot_hash = sha256(candidates)` and
`policy_hash = sha256(policy)` (`JR:src/router.ts#L310-L322`).

**Gap:** our journal and metrics record `state_sha256` but not which option set and which
policy/instruction text produced a choice. When catalogs refresh, prices change or the
selection instruction is edited, decisions from different regimes become indistinguishable in
stats and evals.

**Research:**
- Hash the sorted option list (model, effort, purpose, price) and the instruction text plus
  `[policy]` config. Write both into the journal record and as a low-cardinality label (a short
  prefix) for VictoriaMetrics.
- Check label cardinality: one value per catalog/price refresh should be fine.

**Cost:** small, about half a day with tests.

### 2. Confidence gate on the direct Choice

**JevRouter:** if Jev's confidence is below `min_confidence` (default 0.55) the result is
`no_decision` and the host falls back (`JR:src/router.ts#L385-L402`, `JR:src/manifest.ts#L9-L18`).

**Gap:** we store the Choice `confidence` but always apply the choice. Only the factor policy
uses confidence thresholds (`lib/router_factors.py:70,159-176`).

**Research:**
- Pull the confidence distribution from the journal or VM before choosing a threshold.
- Decide what low confidence should do:
  - (a) leave the launch unchanged (fail-open, like errors);
  - (b) take the factor-policy pick;
  - (c) bump to the next more capable option.
- Measure how often each would fire and how often it would have changed the outcome.

**Note:** JevRouter's gate checks Jev's confidence in its own top pick even after the router has
substituted another candidate (`JR:src/router.ts#L396`). Do not copy that: gate on the
probability of the option we actually apply.

**Cost:** small to implement; the threshold needs data.

### 3. Two-stage selection for large option sets

**JevRouter:** if candidates exceed `single_stage_max_candidates` (32), it asks a coarse Choice
over all of them, keeps the top-K (8) by probability, then asks a final Choice over those
(`JR:src/router.ts#L336-L365`). Both raw responses are kept.

**Relevance:** our options are every (model, effort) pair. Claude is 4 aliases × up to 5
efforts. Codex grows with every new model and effort level. A long criteria list costs input
tokens and may dilute Jev's distribution.

**Research:**
- Count current option totals per agent from the journal and the catalogs.
- In `eval/`, compare single-stage vs two-stage on the same cases: quality, latency (two
  sequential calls must fit the 3 s default / 8 s max budget), and cost.

**Caveat:** JevRouter merges coarse and final probabilities into one ranking
(`JR:src/router.ts#L359`). If we do this, keep the stages separate in records.

**Cost:** medium; worth it only past roughly 30 options or if the eval shows a quality gain.

### 4. Split model and effort into separate questions

**Idea:** derived from JevRouter's multi-question support; JevRouter itself does not do this.
Instead of one Choice over all (model, effort) pairs, ask:
- one Choice over models;
- one Score for effort, with ordered levels;

all in a single request. The candidate count drops from M×E to M. Effort becomes an ordinal
judgement rather than one of many flat options.

**Risks:**
- Model and effort are not independent. A cheap model at high effort may be the right answer
  where an expensive model at low effort is not.
- Supported efforts differ per model, so the Score must be mapped to the nearest supported
  level (`lib/router_factors.py:select` already does this mapping).

**Research:** an eval on a shared case set comparing three strategies:
- the current pair Choice;
- the split Choice + Score;
- the factor policy.

This depends on gap A below.

**Cost:** 1–2 days, mostly eval runs.

### 5. Ideas noted but low priority

- **Policy filter with recorded override.** JevRouter's filter rules (availability, permissions,
  risk; `JR:src/router.ts#L498-L517`) do not map onto model routing. If we ever block options
  after Jev answers instead of before, its `fallback.type/reason` record shape is a good template.
- **Optional decision cache.** Off by default (`JR:src/runtime.ts#L30-L31`). Our tasks are
  rarely repeated verbatim, so the hit rate is likely near zero; skip unless the journal shows
  repeats.
- **Plan / multi-step routing** (`route` vs `plan`). Not applicable: we route each launch
  independently. It could matter if Jev were asked to pick a subagent type as well as a model.

## Not to copy

- 15–20 s fixed timeouts with no retry (`JR:src/provider.ts#L105,L149`). Too long for a launch hook.
  Ours: one deadline of 3 s by default, 8 s max, and one retry on 429/5xx that must fit the deadline.
- The unauthenticated local HTTP `serve` endpoint (`JR:src/cli.ts#L172-L183`).
- Spawning MCP servers with the full `process.env`, which passes Jev keys to them
  (`JR:src/mcp.ts#L52-L53`).
- Plaintext prompts in receipts by default. We mask credentials and keep the journal at mode 0600.
- Relying on CLAUDE.md/AGENTS.md for the agent to choose to route. That is the opposite of our
  hook design.

## Our own gaps found during this comparison

These are not from JevRouter, but they block or affect the items above:

- **A. No eval for the direct Choice (0.5+).** `eval/run.py` covers the pre-0.5 tier router;
  `eval/factors_run.py` covers only the factor policy. Items 2–4 need such an eval first.
- **B. `bin/subagent-model-router` is 2,290 lines.** It mixes config, the Jev client, both
  catalogs, hook logic and commands. Extracting the Jev client and option building into `lib/`
  would make items 1–4 easier to test.
- **C. Dead code.** `lib/router_claude_model.py` and `lib/router_runtime.py` are used only by tests,
  and `TASK_FALLBACK_CHARS` is unused.
- **D. Stale docs.** `README.md` still opens with "Version 0.5.0". `check --live` always probes
  Codex options.
