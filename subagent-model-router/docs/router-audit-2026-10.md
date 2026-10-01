# subagent-model-router 0.6.1: audit report (2026-10)

This report replaces the earlier research note on other Jev-based routers. Its useful facts are carried over in
[section 4](#4-what-we-adopt-from-the-previous-research). The work items live in [TODO.md](../TODO.md).

Conventions:

- Paths are relative to `subagent-model-router/`. `bin` means `bin/subagent-model-router`.
- `[V]` marks a claim the research audit read on a vendor page or paper (an official or primary source). The
  web fact-check re-confirmed only a subset of them; [§9](#9-sources) lists which.
- `[U]` marks a claim with no external confirmation: an inference, an estimate, a second-hand number, or a
  recommendation.
- "Measured" means it was measured in this repository, in sandboxed repros or in the shipped eval data.

## 1. Summary

**Scope.** The audit covered the subagent-model-router plugin, version 0.6.1, at BASE_SHA
`8d64156c5b124ac3dd244afb9b446d856072adec`. It looked at four areas:

- the hook core: request building, Jev client, selection and launch rewriting;
- telemetry, dashboards and evaluation;
- catalogs, prices, update notices and support code;
- research: prices, vendor guidance, literature, and the earlier research backlog.

**Method.**

- Four audits, one per area, each produced a findings list.
- Four adversarial verifications then re-checked those findings:
  - hook core (CORE-01..08) and research items N1, N2, N4;
  - telemetry (TEL-01, 02, 04..08, 10, 13) and CORE-09..19;
  - support (SUP-01..19), which also found two new issues;
  - a web fact-check of every external claim.
- When the auditor and the verifier disagree, the verifier wins.
- Findings that no verifier re-checked keep the auditor's severity and are marked **unverified (auditor only)**:
  - TEL-03, TEL-09, TEL-11, TEL-12, TEL-14..17;
  - research items N3, N5, N6, N7, N8 and the backlog items.
- All repros ran sandboxed:
  - HOME, TMPDIR, the XDG directories and the config path pointed into throw-away directories;
  - Jev was the repo's fake server on loopback (`tests/fake_jev.py`);
  - Claude and Codex were fake binaries;
  - VictoriaMetrics was a fake HTTP server on loopback.
- No real client binaries were run. Apart from the fact-check, nothing made network calls.

**Headline conclusions.**

1. **There is no evidence that per-call Jev routing beats a static default** (TEL-03, unverified).
   - The default Choice path has never been evaluated, and neither has the code-owned `select()`.
   - The factor eval is in-sample, and its bands are circular.
   - Jev itself is cheap: about $0.00003–0.00004 and 0.4–0.6 s per call, measured on the smaller eval
     requests. At production request size the estimate is about $0.00015–0.0002 and 0.6–1.0 s [U]. The open
     question is whether its decisions are worth anything.
2. **One high-severity bug: CORE-01.**
   - A routed Claude launch with an effort replaces the built-in general-purpose system prompt with the
     two-sentence body of the effort agent.
   - Haiku keeps the built-in prompt, because it has no effort support. So the prompt variant is confounded
     with the model, and any quality comparison between tiers is confounded too.
3. **The default configuration pays for work that changes nothing.**
   - Shadow factor questions ride on every request: +26.8% bytes on Claude and +36.8% on Codex (CORE-03,
     TEL-05).
   - A hung Jev endpoint costs the full timeout (3.07 s) on every launch, because the client has no circuit
     breaker (CORE-02).
4. **The Codex defaults are stale, and the effort cap leaks** (N1, N2).
   - In practice the rank ladder is luna → 6-sol → 6-sol → astra.
   - `gpt-6.1-sol`, the vendor's recommended subagent model, is never picked.
   - `ultra` and `max` can be launched both through the Choice and through the policy's effort clamp.
5. **Cost-per-solved-task cannot be measured yet.**
   - No per-launch outcome or cost is joined to a decision (N8, unverified).
   - Decisions carry no provenance hash (backlog item 2).
   - On the VictoriaMetrics backend, events can be dropped whole, cost included, once the series cap fills
     (TEL-02). The main stats query can also go blank (TEL-01).
6. **Price data is fragile** (SUP-05, SUP-01).
   - The scraper needs exact headings and column names, and it refuses redirects.
   - `check` reports "ready" even while prices are unknown.
7. **Superfluous code.**
   - About 3,200–3,400 lines could go, test code included. About 1,400 of them are optional dashboard extras.
   - Monitoring alone is about 8,000 lines, about 3.5× the size of `bin` ([§3.8](#38-superfluous-parts)).
8. **Recommended strategy: static per-client defaults plus escalation on an observed failure.**
   - Claude: Opus 5.5 at `medium`. Codex: `gpt-6.1-sol` at `medium`.
   - Keep Jev in shadow (sampled) until a paired eval shows two things together: at least 15% lower cost per
     solved task, and a pass rate within 2–3 points ([§5](#5-optimal-subagent-model-and-run-strategy),
     [§6](#6-measurement-plan)).

## 2. Verified findings

The columns are:

- **verdict**: the verifier's verdict. CONFIRMED, PARTIAL, or "unverified (auditor only)" where no verifier
  looked.
- **final severity**: the severity after verification.
- **was**: the auditor's severity, given only where it changed.

SUPV-N1 and SUPV-N2 are new issues the support verifier found (it numbered them N1 and N2). They are renamed here
so they do not clash with the research items N1 and N2.

| id | area | verdict | final severity | statement |
|---|---|---|---|---|
| CORE-01 | hook core | CONFIRMED | high | Routed Claude launches with an effort swap the built-in general-purpose prompt for the two-sentence effort-agent body. No-effort models (Haiku) keep the built-in prompt, so the prompt is confounded with the model. |
| CORE-02 | hook core | PARTIAL | low (was medium) | No circuit breaker: a hung Jev costs the full timeout on every launch. A refused connection fails fast (0.11 s). |
| CORE-03 | hook core | CONFIRMED (facts) | low (was medium) | The default `policy.mode = "shadow"` adds 8 factor questions to every request (+2,279 B, +26.8% on Claude) with no routing effect. The claimed latency delta is unproven. |
| CORE-04 | hook core | PARTIAL | low (was medium) | The Choice request carries `visible_task`, a per-task USD estimate, full price records and `ensure_ascii` escaping. The prefix-caching argument is refuted. |
| CORE-05 | hook core | PARTIAL | low (was medium) | With no config, or with `enabled = false`, the hook still journals description, cwd, host, user and session. This is documented, but README:236 says "Entirely". |
| CORE-06 | hook core | PARTIAL | low, design (was medium) | Active factor policy: effort follows the reasoning factor only, so a frontier model can launch at `low`. This is a non-default mode, and the quality effect is a hypothesis. |
| CORE-07 | hook core | PARTIAL | low (was medium) | Every hook process pays about 53–61 ms of Python start-up, against about 14 ms for bare `python3`. Whether the matcher is anchored depends on host semantics (unverified). |
| CORE-08 | hook core | PARTIAL | low, documented trade-off | The policy sorts unpriced models last and never picks unranked ones; both are documented. Its output-only cost key assumes equal input/output price ratios, which is false for OpenAI. |
| CORE-09 | hook core | CONFIRMED | low | `claude.route_types` and Codex `route_agent_types` can only narrow routing. Built-in Explore/explorer are never routed, which is undocumented. |
| CORE-10 | hook core | CONFIRMED | low | Claude treats `model: null` as an explicit choice and skips. Codex treats null as absent. |
| CORE-11 | hook core | CONFIRMED | low | The five effort agents are advertised to the parent. A parent that picks one directly runs unrouted at a fixed effort (reason `type`). |
| CORE-12 | hook core | PARTIAL | low | Factor parsing: ties break downward, and an unknown effort label can win the clamp. The `impact < 2` discount is intended, so this is README drift (overlaps CORE-17). |
| CORE-13 | hook core | CONFIRMED | low | Redundant work per routed call: config loaded twice, price cache parsed twice, effort definitions re-read from disk at three call sites. |
| CORE-14 | hook core | CONFIRMED | low | Journal and outbox I/O run before the hook writes its answer to stdout. |
| CORE-16 | hook core | CONFIRMED | low | Codex: while a catalog fetch keeps failing, every `spawn_agent` spawns another background refresh. |
| CORE-17 | hook core | PARTIAL | low | Doc drift at README:104, README:113-114, README:236 and the `lib/router_factors.py` docstring. README:8, :278 and :307 are accurate historical statements, not drift. |
| CORE-18 | hook core | CONFIRMED | low | Dead and test-only code: `TASK_FALLBACK_CHARS`, `router_runtime`, `router_claude_model`, most of `router_claude_state`. The `/proc` walkers and the legacy migration are not dead. |
| CORE-19 | hook core | CONFIRMED (by design) | low | Top-level `mode = "shadow"` (opt-in) pays the full Jev call and shows a message while changing nothing. |
| TEL-01 | telemetry/eval | CONFIRMED (mechanism) | medium (was high) | The VM stats "calls" query groups by 16 labels and fails above 120 series. The main panels then show "No data", with a visible "Failed queries: calls" notice. |
| TEL-02 | telemetry/eval | PARTIAL | medium (was high; high only where VM is the primary backend) | The 4,096-series outbox cap is never pruned. After about 26 projects per agent, any event that needs a new series is dropped whole, cost included. |
| TEL-03 | telemetry/eval | unverified (auditor only) | high | The eval cannot support "cheaper without quality loss": Choice and `select()` are unevaluated, bands are circular, results are in-sample, there is no outcome data, and the production request shape is unmeasured. |
| TEL-04 | telemetry/eval | PARTIAL | low (was medium) | A VM payload over 2 MiB stops delivery for good, with an empty `last_error`. The trigger is about 2,800 or more new combinations between snapshots. Untested. |
| TEL-05 | telemetry/eval | CONFIRMED | low (was medium; medium only if a measurement shows timeout impact) | The merged Choice-plus-factor request has never been measured. The 1.3–2× and 100–300 ms figures are estimates. |
| TEL-06 | telemetry/eval | PARTIAL | low (was medium) | The post-fix factor eval never separates the P01/P03 pair, and the jsonl summary is stale. "100% hinges on 0.5 vs 0.52" is refuted. |
| TEL-07 | telemetry/eval | PARTIAL | low (was medium) | The local journal records no hook duration, so the Hook row in the local HTML is empty. The terminal claim is wrong. |
| TEL-08 | telemetry/eval | CONFIRMED | low (was medium) | Grafana panel 11 filters `reason="choice"` and so ignores policy-applied launches. This is display-only, and the panel description scopes it. |
| TEL-09 | telemetry/eval | unverified (auditor only) | medium | About 100 of the 154 series per event are dashboard-only histograms, and `calls_total` carries 19 labels. |
| TEL-10 | telemetry/eval | CONFIRMED | low | Dead legacy tier telemetry: `rule:*` reasons, a tier label that is always "none", rule-only histograms, an unused `_is_choice`. |
| TEL-11 | telemetry/eval | unverified (auditor only) | low | The hook writes telemetry before stdout, loads config twice, and leaves enqueue time (2.59 ms mean) out of the hook duration. |
| TEL-12 | telemetry/eval | unverified (auditor only) | low | The cost-rate query is duplicated. Two local stats readers use different default periods. The help text says "(VM)" for options that also work locally. |
| TEL-13 | telemetry/eval | CONFIRMED | low | Grafana panel 51 is titled "potential savings", which contradicts `monitoring.md:117`. |
| TEL-14 | telemetry/eval | unverified (auditor only) | low | The README Evaluation section omits the factor eval. |
| TEL-15 | telemetry/eval | unverified (auditor only) | low | The local journal grows without bound, and stats rescans the whole file. |
| TEL-16 | telemetry/eval | unverified (auditor only) | low | Telemetry enqueue swallows every exception, the sqlite busy timeout is 0.1 s, and the hook ignores the result. |
| TEL-17 | telemetry/eval | unverified (auditor only) | low | The legacy tier eval (`eval/run.py`, `eval/cases.json`, `eval/README.md`) cannot run but is still shipped. |
| SUP-01 | catalog/prices/notices | PARTIAL | low (was medium) | `check` prints "ready" while prices are unknown. The 24 h negative cache is intended. |
| SUP-02 | catalog/prices/notices | PARTIAL | low (was medium) | With `enabled = false`, update notices and the `claude --version` probe still run. README:236 "Entirely" overclaims. |
| SUP-03 | catalog/prices/notices | PARTIAL | low (was medium) | A forced async catalog refresh runs on every SessionStart, including `/clear` and compaction. This is documented as intended. |
| SUP-04 | catalog/prices/notices | CONFIRMED (mechanism) | low (was medium) | A group-writable parent of the config directory silently disables update notices and the client-version cache. `check` is silent about it. |
| SUP-05 | catalog/prices/notices | CONFIRMED | medium | The price parser needs exact headings and headers and refuses redirects. Any upstream edit leaves prices unknown or stale, with no error. |
| SUP-06 | catalog/prices/notices | CONFIRMED | low (was medium) | The 64-slot client-version cache loses records through collisions. Only the `agent_version` telemetry label is affected. |
| SUP-07 | catalog/prices/notices | CONFIRMED | low | Start-up cost of about 61 ms per update-notice hook, against 13.5 ms for bare `python3`. |
| SUP-08 | catalog/prices/notices | CONFIRMED | low | 256 update-notice slots with a 30-day lock: sessions that collide on a slot silently get no notice. |
| SUP-09 | catalog/prices/notices | CONFIRMED (understated) | low | An fsync and a `/proc` walk on every prompt. The finding missed the Codex subprocess (SUPV-N1). |
| SUP-10 | catalog/prices/notices | CONFIRMED (location widened) | low | `router_claude_model.py` is test-only. `router_claude_state.py:29-69`, `117-141` and `144-263` are dead too. |
| SUP-11 | catalog/prices/notices | CONFIRMED | low | Four `/proc` ancestor walkers, each with its own name, depth and ELF rules. |
| SUP-12 | catalog/prices/notices | CONFIRMED | low | The background refresh keeps old descriptions, while the `check` path adopts the new ones. |
| SUP-13 | catalog/prices/notices | CONFIRMED | low | One non-JSON stdout line from Claude aborts the whole catalog fetch. Unlikely in practice. |
| SUP-14 | catalog/prices/notices | CONFIRMED | low | `http.client.IncompleteRead` escapes the price fetch. No record is written, so every hook spawns a worker while the failure lasts. |
| SUP-16 | catalog/prices/notices | CONFIRMED | low | An existing Codex cache dir is not checked. The Claude catalog temp dir is hard-coded and ignores TMPDIR. |
| SUP-18 | catalog/prices/notices | CONFIRMED | low | "Prices never reach Jev" (`config.example.toml:22`, SKILL.md:122) contradicts the code, which sends `price_reference`. |
| SUP-19 | catalog/prices/notices | PARTIAL | low | Only SKILL.md:162 is incomplete. The README:144 claim is wrong, README:8/278/307 are historical, and the `models_cache.json` claim is unverified. |
| SUPV-N1 | catalog/prices/notices | NEW (verifier) | low-medium | Under Codex, update-notice runs `codex plugin list` synchronously (1 s budget) on any cache miss. A cwd change is a miss. |
| SUPV-N2 | catalog/prices/notices | NEW (verifier) | low | A 0755 config dir passes `load_config`, but update notices go silent, because they require exactly 0700. `check` says nothing. |
| N1 | research | CONFIRMED | medium (was medium–high) | The Codex default ranks are stale or dominated: `gpt-6.1-sol` is unranked and never picked, and 5.4, 5.5, 5.6-luna, 5.6-sol and terra never win. |
| N2 | research | PARTIAL | medium | `ultra`/`max` are reachable through the Choice. The policy clamp can also return them when a model lacks `xhigh`, which goes further than the claim. |
| N3 | research | unverified (auditor only); mechanism confirmed under CORE-01 | benefit medium–high | Routed Claude calls change the system prompt. Make it an explicit eval arm. |
| N5 | research | unverified (auditor only) | benefit medium | Claude rank 1 is Haiku 4.5: no effort support, 200K context, a 4,096-token cache minimum, retirement on or after 2026-10-15. |
| N6 | research | unverified (auditor only) | benefit high if the eval confirms it | There is no deterministic static arm or cascade. `prior_failure` is judged from text, not observed. |
| N7 | research | unverified (auditor only); premise supported by the CORE-08 verifier note | benefit medium | The policy cost key is the output rate only. Use a blended or measured cost. |
| N8 | research | unverified (auditor only) | enabler | There is no measurement plumbing for per-launch cost and outcome. Background subagents return no usage to PostToolUse. |

**Material disagreements between auditor and verifier** (the verifier wins):

- CORE-02: the "when Jev is down" half is wrong. A refused connection fails in 0.11 s and a persistent 503 in
  0.3 s. Only a hung endpoint costs the full timeout.
- CORE-03: the request sizes differ by fixture. The auditor measured 11,394 B against 9,115 B, the verifier
  10,776 B against 8,497 B; the delta is the same, 2,279–2,280 B. The 598 ms vs 399 ms latency comparison sets
  two different evals side by side, so it proves nothing.
- CORE-04: the caching premise is refuted. `state` is serialized first, nothing shows that Jev caches prefixes,
  and the static prefix (about 600 tokens) is below the 1,024-token minimum. The payload bloat is real.
- CORE-05: the roughly 60 ms is interpreter start-up, so an early return would not remove it. The privacy part
  stands, and README:52-53 documents it.
- CORE-06: "the explanation is wrong" is false, because the systemMessage shows no drivers. The stale `drivers`
  field is a labelling nit.
- CORE-07: whether the matcher is anchored depends on host semantics, which nobody verified. It is a cleanup item.
- CORE-08: this is a documented trade-off, not a bug. The verifier adds that the equal-ratio premise is false
  for OpenAI (5× to 8×): with an input-rate key, level 2 would pick `gpt-5.6-terra`, not `gpt-6-sol`.
- CORE-12: the `impact < 2` verified discount is intended by the labelled eval. Only the README wording drifts.
- CORE-17 and SUP-19: README:8, :278 and :307 are historical and still accurate. The README:144 claim is wrong.
- CORE-18: the `/proc` walkers are live duplicates (see SUP-11). The legacy config migration (`bin:205-224`) is
  an intentional shim, documented at README:278.
- TEL-01: not silent, because a failure notice is printed. Only the optional VM backend is affected.
- TEL-02: the growth driver is distinct projects (+155 series each), not upgrades (+1 per combination).
- TEL-04: a realistic 4,096-series policy mix is about 1.15 MB, under the 2 MiB cap.
- TEL-06: with a 0.61 threshold the result is still 92/92. The pair is still never told apart, and the summary
  is stale.
- TEL-07: the terminal never showed hook latency. Only the Hook row in the local HTML is empty.
- TEL-13: the cited line (:2782) is panel 57's legend, and the panel description hedges.
- SUP-01..04, SUP-06: dropped from medium to low. For SUP-01..03 this is because the behaviour is documented as
  intended.
- SUP-09: understated. It missed the synchronous `codex plugin list` (SUPV-N1).
- N1: dropped to medium, because it changes launches only in `active` mode. `gpt-5.6-luna` is dominated as well.
- N2: wider than claimed. The policy's effort clamp can also launch `max`/`ultra`.
- Typo in the core verifier's own summary: it says "N1 and N4 hold as stated, N4 is refuted". Its per-item
  verdicts are the authoritative ones: CORE-01 and N1 confirmed, N4 refuted.

**Refuted or dropped claims**

| id / claim | outcome | reason |
|---|---|---|
| CORE-15 (float equality in the winners check can discard a paid answer) | refuted, severity none | Both sides of the comparison come from the same table, so equality is exact. Rejecting a choice that contradicts its own probabilities is intended (`bin:429`, `bin:454-456`). |
| N4 (effort can be silently overridden by `CLAUDE_CODE_EFFORT_LEVEL`) | refuted; a low residual remains | `bin:1335-1337` skips routing when that variable, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` or the coordinator variable is set; `tests/test_claude_state_integration.py:52` covers it. Residual: `maxEffortLevel` and settings caps are not detected, and `check` does not warn (documented at SKILL.md:56-58). |
| SUP-15 (caches grow without limit) | dropped | Growth is bounded: a Claude catalog over 2 MiB becomes `{}`, and a price record with more than 512 models is invalid and gets refetched. |
| SUP-17 (codex-trust accepts the plugin name from any marketplace) | dropped | Deliberate and tested (`tests/test_router.py:921-928`). The exact command must still match (`bin:2102`), and `--dry-run` is available. Accepting `subagent-model-router@<marketplace>` for any marketplace is intended. |
| CORE-04: the Choice payload "defeats prefix reuse" | refuted part | See the disagreement above. |
| CORE-02: "when Jev is down, every launch pays the full timeout" | refuted part | Down endpoints fail fast. Only hung ones cost the timeout. |
| CORE-05: an early return removes about 60 ms | refuted part | That time is interpreter start-up. |
| CORE-06: the user-facing explanation is wrong | refuted part | No drivers are shown. |
| CORE-18: the walkers and the legacy migration are dead | refuted part | Both are live or intentional. |
| CORE-17 / SUP-19: README:8, :278 and :307 drift; README:144 omits catalog discovery | refuted part | Historical and accurate; README:144-145 does mention discovery. |
| TEL-06: "100% depends on 0.5 vs 0.52" | refuted part | A 0.61 threshold still gives 92/92. |
| TEL-07: "terminal hook latency is always None" | refuted part | The terminal never shows hook latency. |
| Research [P6] wording: "fixed-tier baselines and share-matched content-blind allocation are necessary controls" | wrong quote | The abstract says: "Fixed-tier baselines and selected-tier distributions are therefore necessary controls in router evaluation." "Share-matched content-blind allocation" appears only as one router's comparison point. |
| Research gap D: the "Version 0.5.0" line in README:8 is stale | refuted part | README:8 is a historical statement and still accurate (CORE-17 verifier). |

## 3. Bugs, gaps, superfluous parts

Each group lists finding ids, file:line evidence and the recommended fix. The work items are in
[TODO.md](../TODO.md).

### 3.1 Prompt and routing correctness

- **CORE-01 (high), N3 (unverified).** Evidence:
  - `bin:1284-1291` (`apply_selection`) sets `subagent_type` to `subagent-model-router:effort-<level>` whenever
    the selected effort is not None.
  - `bin:1047-1048` offers `(model, None)` for models without effort support.
  - Every `agents/effort-*.md` body reads "Execute the task supplied in the delegation prompt. Respect its scope,
    permissions, constraints, required checks, and requested output. Do not expand the assignment." [C1] says:
    "The body becomes the system prompt … not the Claude Code system prompt."
  - Repro results:
    - Choice index 0 gives `general-purpose` + `haiku`;
    - index 1 gives `effort-low` + `sonnet`;
    - the last index gives `effort-max` + `fable`.
  - README:36-40 does not say that the built-in prompt is replaced.

  **Fix:**
  - Give haiku and non-haiku launches the same prompt variant within any arm.
  - Rewrite only `model` (keeping `general-purpose`) when the target effort equals what the launch would get anyway.
  - Use an effort agent only when the effort must differ, and record the prompt variant.
  - Run the N3 A/B arm (built-in plus `model` against the effort agent at the same model and effort). Only then
    decide whether to enrich the bodies.
- **N1 (medium), CORE-08 (low).** Evidence:
  - `lib/router_factors.py:74-78` (DEFAULT_RANKS has no `gpt-6.1-sol`).
  - `:237` drops unranked models.
  - `:248-255` sorts by output rate, then rank, then name.
  - `config.example.toml:43-45`.
  - With the [O1] prices, the levels pick luna / 6-sol / 6-sol / astra. Ranking `gpt-6.1-sol` at 3 still loses
    the name tie.

  **Fix:**
  - Replace `gpt-6-sol` with `gpt-6.1-sol` at rank 3, or rank both and break ties on a blended rate.
  - Drop retired and dominated entries ([§5.3](#53-per-client-defaults)).
- **N2 (medium).** Evidence:
  - `bin:706-715` takes efforts straight from `supported_reasoning_levels`; `bin:1066` offers every one.
  - Repro: the Choice launched `gpt-5.6-terra` with `ultra`.
  - The `_effort_for` clamp in `lib/router_factors.py` returns `ultra` or `max` when a model lacks `xhigh`.
  - [O2]: "Ultra uses subagents".

  **Fix:** exclude `ultra`, and `max` by default, from Choice options and from the policy clamp.
- **CORE-06, CORE-12 (low).** Evidence: `lib/router_factors.py:150` (ties break downward), `:178-209` and
  `:203` (`effort_index = reasoning`), and `:220-229` (an unknown effort label wins).

  **Fix:** in active mode, give the effort a floor derived from the capability level, and reject effort labels
  that are not in `EFFORT_ORDER`.
- **CORE-10, CORE-09, CORE-11 (low).** Evidence:
  - `bin:1338` treats a Claude `model: null` as explicit; `bin:1342` treats a Codex null as absent.
  - `bin:1361` (Claude) and `bin:1365` (Codex) hard-code the routable types, so `route_types` and
    `route_agent_types` can only narrow them (SKILL.md:45, `config.example.toml:32`).
  - The effort agents carry no internal marker.

  **Fix:**
  - Treat null the same way on both clients.
  - Make the route lists real, or document that they only narrow, and that Explore/explorer are never routed.
  - Describe the effort agents as router-internal.
- **N5 (unverified).** `lib/router_factors.py:75` ranks `haiku` 1. Facts for Haiku 4.5 [A2] [A4]:
  - no effort support;
  - 200K context;
  - a 4,096-token cache minimum;
  - retirement "not sooner than October 15, 2026".

  **Fix:** offer rank 1 only for verified, low-impact tasks, and review the choice when retirement is announced.
- **N4 residual (low).** `maxEffortLevel` and settings caps are not detected.

  **Fix:** have `check` warn about them, and record intended against effective effort.

### 3.2 Hook-path cost and latency

- **CORE-02 (low).** Evidence:
  - `bin:507-542` (`_exchange`), `bin:545-571` (`ask_jev`), `bin:1380-1393`; `bin:258-260` caps the timeout
    at 8 s.
  - A hung endpoint costs 3.07 s on every call. Two consecutive hooks took 2.09 s and 2.06 s, so nothing is
    remembered between calls.

  **Fix:**
  - After a timeout, write a skip marker for about 120 s.
  - Lower the default timeout to about 1.5 s. Measured Jev latency on the smaller eval requests: p90 0.72 s,
    max 0.90 s. At production size it is estimated at 0.6–1.0 s [U], so confirm the value against the
    production-size measurement first.
- **CORE-03, TEL-05 (low).** Evidence:
  - `lib/router_factors.py:70` (default `shadow`), `bin:1383-1385` and `bin:1402-1405`,
    `config.example.toml:25`, README:123.
  - The 8 questions add 2,280 B to the request.
  - The merged request has never been measured (`eval/factors_README.md:9`, `eval/factors_run.py:329`).

  **Fix:** default `policy.mode` to `off`, or sample it. Keep one mechanism once the eval picks it.
- **CORE-04 (low).** Evidence:
  - `bin:1120-1175` (`selection_questions`; `:1126-1133`, `:1160-1167`) and `lib/router_token_budget.py`.
  - The wire body is 11,706 B, against 11,394 B compact, because of `ensure_ascii`.
  - Fixed text makes up 96–97% of the request (appendix).

  **Fix:**
  - Drop `visible_task` and the per-task USD estimate.
  - Send only `{input, output, status}` per model.
  - Serialize with `ensure_ascii=False`.
- **CORE-07, SUP-07 (low).** Evidence:
  - `bin:22` imports `router_token_budget` at top level; `bin:288`; `bin:336` (`DEFAULT_RULES`).
  - `hooks/hooks.json:5` matcher `"Agent|spawn_agent$"`.
  - A non-agent hook takes 55 ms, against 13.8 ms for bare `python3`.
  - Compiling `bin` costs 11.6–30.8 ms, and importing `router_telemetry` 11.6–25.3 ms.

  **Fix:**
  - Add a thin launcher (about −20 ms).
  - Import lazily.
  - Merge update-notice and telemetry-kick into one process.
  - Anchor the matcher.
- **CORE-13, CORE-14, TEL-11 (low; TEL-11 unverified).** Evidence:
  - `bin:1351` and `bin:1481` both load the config.
  - The price cache is parsed twice (`lib/router_model_prices.py:248`, `:344`).
  - Effort definitions are read from disk (`bin:1014-1026`, called at `bin:1053`, `bin:1288` and `bin:1431`).
  - Journal and outbox I/O run before stdout (`bin:1463-1499`).
  - Enqueue takes 2.59 ms mean and 9.48 ms max.

  **Fix:** load each input once per call, write stdout first, then telemetry, and include enqueue in the
  duration.
- **CORE-19 (low, by design).** Shadow routing pays the full Jev call (README:237).

  **Fix:** sample shadow calls, or run them detached, and suppress the message.
- **SUPV-N1 (low-medium), SUP-09 (low).** Evidence:
  - `lib/router_update_notice.py:146` runs `codex plugin list --marketplace <marketplace> --json` with a 1 s
    budget.
  - Its cache key includes the cwd (`:236`), and a miss calls it inline (`:260-266`).
  - `:277-286` does an fsync and a `/proc` walk on every prompt.

  **Fix:** move the plugin-list probe off the prompt path (detached, or cached per binary only), and drop the
  per-prompt fsync.

### 3.3 Evaluation and measurement gaps

- **TEL-03 (high, unverified), backlog item 1, gap A.** Evidence:
  - `eval/factors_run.py:288` is factor-only.
  - The bands are circular (`eval/factors_run.py:370-381`).
  - The results are in-sample (`eval/factors_results-20260927.md:19-23`).
  - The production request shape is unmeasured (`bin:1385`; README:304-307).
  - There is no subagent outcome data.

  **Fix:** build the paired strategy eval described in [§6](#6-measurement-plan).
- **N6 (unverified).** There is no static mode. `prior_failure` is a Jev judgement made from text
  (`lib/router_factors.py:64`, `:200-202`), not an observed failure.

  **Fix:** add a static-default arm with escalation on an observed failure.
- **N8 (unverified).** Since v2.1.198, subagents run in the background by default, so PostToolUse returns
  `async_launched` with no usage [C4].

  **Fix:** join OTel cost and token records by `agent_id` [C5] with the decision record.
- **TEL-06 (low).** The P01/P03 pair is never separated. The jsonl summary at line 94 is stale (it still shows
  0.9565 within band and `"4->3": 4`).

  **Fix:** add a held-out case set, and make the runner fail when a summary does not match its data.
- **TEL-14, TEL-17 (low, unverified).** README:304-307 omits the factor eval. `eval/run.py` (131 lines),
  `eval/cases.json` and `eval/README.md` cannot run.

  **Fix:** document the factor eval, and archive or delete the legacy harness.

### 3.4 Telemetry and dashboards

- **TEL-02 (medium).** Evidence:
  - `lib/router_telemetry.py:33-34` sets `MAX_SERIES = 4096`.
  - `:643-646` drops the whole event at the cap, and nothing prunes.
  - `monitoring.md:56-57` gives no recovery procedure.

  **Fix:**
  - Prune superseded series.
  - Move version labels off the per-call series.
  - Degrade per point instead of per event, and always keep the cost, latency and error counters.
- **TEL-01 (medium).** Evidence: `lib/router_dashboard.py:21` (`MAX_SERIES = 120`), `:46-47`, and `:264` (16
  group-by labels).

  **Fix:** split the query into small aggregates, or use `topk`, and add a test with more than 120 series.
- **TEL-04, TEL-16 (low; TEL-16 unverified).** Evidence:
  - `lib/router_telemetry.py:750-752` raises `payload_size`.
  - `:763` (`_prepare`) sits outside the `try` that records `last_error`, and `:811-813` swallows the error.
  - `:665-666` swallows enqueue exceptions; `:360` sets a 0.1 s busy timeout; `bin:1494-1495` ignores the result.

  **Fix:** record `last_error`, split oversized payloads, and count enqueue failures.
- **TEL-07 (low).** Evidence: `bin:1486-1487` (local journal) against `bin:1491-1493` (VM path), and
  `lib/router_dashboard.py:670`.

  **Fix:** write `hook_ms` to the journal.
- **TEL-08, TEL-13 (low).** Evidence: `grafana/subagent-model-router.json:704` (panel 11, `reason="choice"`;
  compare `lib/router_dashboard.py:270`), and panel 51's title against `monitoring.md:117`. No panel shows
  `dropped_events` or a stalled `payload_size` (verifier note).

  **Fix:** use `reason=~"choice|policy"`, rename panel 51, and add a delivery-health panel.
- **TEL-12, TEL-15 (low, unverified).** Evidence:
  - `lib/router_dashboard.py:279-280`.
  - Two local readers: `bin:1645-1673` (`days=None`) and `bin:1676-1743` (`days or 7`).
  - The help text near `bin:2232-2244`.
  - An unbounded journal (`bin:1446-1460`).

  **Fix:** use one reader with one default period, and rotate the journal.

### 3.5 Prices and catalogs

- **SUP-05 (medium), SUP-14 (low).** Evidence:
  - `lib/router_model_prices.py:26-30` and `:67-87` (exact heading and header: 9 columns for OpenAI, 6 for
    Claude).
  - `:154-169` (`_NoRedirect` at :161).
  - `:168` and `:331` (`IncompleteRead` escapes).

  **Fix:**
  - Match columns by keyword.
  - Follow same-host HTTPS redirects.
  - Add a `parse_failed` status.
  - Catch `http.client.HTTPException`.
  - Consider shipping a versioned fallback price table.
- **SUP-01 (low).** Evidence:
  - `lib/router_model_prices.py:267-268` (`_ready`), `:271-280` and `:338-347`; `bin:1775-1783`.
  - Stale prices count as known (`lib/router_factors.py:216`).

  **Fix:** count prices as ready only when they exist, retry with backoff (15 min, 1 h, 6 h), and print
  per-model status in `check`.
- **N7 (unverified), CORE-08.** Evidence: `lib/router_factors.py:214-217` and `:248-255` use the output rate
  only. Input/output price ratios run 5× to 8× on OpenAI. [P8]: in 32% of model pairs, the model with the lower
  listed price costs more.

  **Fix:** use a blended rate built from an observed input/cached/output mix, then a measured cost per task.
- **CORE-16, SUP-03 (low).** Evidence:
  - `bin:928-936`, `bin:864-914` and `bin:829` (a persistent fingerprint mismatch spawns a refresh on every
    spawn).
  - `bin:1523-1525` and `bin:984-992` (`force=True`), `lib/router_claude_catalog.py:314-315`, and
    `hooks/hooks.json:15` (no matcher).

  **Fix:** rate-limit refreshes per fingerprint (for example once per 10 min), and drop the forced SessionStart
  refresh in favour of a 24 h expiry.
- **SUP-12, SUP-13 (low).** Evidence:
  - `bin:902-906` keeps old descriptions, while `bin:1798-1802` and `bin:1829-1832` adopt new ones.
  - `lib/router_claude_catalog.py:137` and `:147-148` (one bad line aborts the fetch).

  **Fix:** use one description rule on both paths, and skip non-JSON lines.

### 3.6 Privacy, config and file safety

- **CORE-05, SUP-02 (low).** Evidence:
  - `bin:1327`, `bin:1370-1371` and `bin:1478-1487` (the journal is written while disabled).
  - `bin:1516-1520` and `bin:1558-1559` (notices and the `--version` probe still run).
  - `lib/router_telemetry.py:28`.
  - README:52-53 and README:236.

  **Fix:** make `enabled = false` an early exit with no journal, no subprocess and no notice, or reword
  README:236.
- **SUP-04, SUPV-N2, SUP-16 (low).** Evidence:
  - `lib/router_claude_state.py:91-99` (`:98` requires exactly 0700) against `bin:309` (rejects only `0o022`).
  - `lib/router_update_notice.py:198`.
  - `bin:757-763` (the Codex cache dir is not checked).
  - `lib/router_claude_catalog.py:104` (a fixed temp directory that ignores TMPDIR).

  **Fix:** use one permission policy everywhere, have `check` report directories that fail it, and honour
  TMPDIR.
- **SUP-06, SUP-08 (low).** Evidence:
  - `lib/router_client_version.py:32` and `:155-168` (64 slots; a record survives n later sessions with
    probability (62/64)^n, which is 0.53 at n = 20).
  - `lib/router_update_notice.py:25`, `:237` and `:253-256` (256 slots, a 30-day lock; 61 of 200 sessions are
    skipped, analytically).

  **Fix:** take the Claude version from the binary path, cache the Codex version per binary, and key notices so
  that sessions do not collide.

### 3.7 Documentation drift

- **SUP-18:** `config.example.toml:22` and SKILL.md:122 say "Prices never reach Jev", but `bin:1116` and
  `bin:1127` send `price_reference`.
- **CORE-17:**
  - README:104 calls the merged request free of extra latency; nobody has measured that.
  - README:113-114 does not match `impact < 2` (`lib/router_factors.py:197`).
  - The `lib/router_factors.py:1-7` docstring says prices never reach Jev.
- **CORE-05 / SUP-02:** README:236 says `enabled = false` turns the router off "Entirely".
- **SUP-19:** SKILL.md:162 is incomplete.
- **TEL-14 (unverified):** README:304-307 omits the factor eval.
- **Research gap D (unverified):** `check --live` probes Codex options whatever the agent (near `bin:1903-1913`).
- **Fix:** one documentation pass, plus a test that greps for the phrases that were removed.

### 3.8 Superfluous parts

| Candidate | Ids | Evidence | Lines removable (estimate from the audits) |
|---|---|---|---|
| Test-only `lib/router_runtime.py` and its tests | CORE-18 | imported only by `tests/test_runtime*.py` | 145 + 119 = 264 |
| Test-only `lib/router_claude_model.py` and the dead parts of `lib/router_claude_state.py`, with their tests | CORE-18, SUP-10 | state `:29-69`, `:117-141`, `:144-263`; production uses only `:71-114` | 260–342 library + 618–713 test |
| `TASK_FALLBACK_CHARS` | CORE-18 | `bin:37` | 1 |
| Four `/proc` walkers merged into one | SUP-11 | `bin:120-141`, `bin:591-604`, `bin:632-646`, `lib/router_client_version.py:71-100` | 55–80 |
| Client-version module reduced to path-derived versions | SUP-06 | `lib/router_client_version.py` (284 lines) | about 220 |
| Shared catalog cache between `bin` and `router_claude_catalog` | SUP-12, SUP-16 | support audit | about 100 |
| Simpler update-notice slots | SUP-08 | `lib/router_update_notice.py:253-256` | about 40 |
| Forced refresh, second `load_config`, separate telemetry-kick command, `route_types` | SUP-03, CORE-13, CORE-07, CORE-09 | see above | about 45 |
| `visible_task` and per-task USD in the Choice request | CORE-04 | `bin:1120-1175` | 30–80 |
| Dead tier telemetry | TEL-10 | `lib/router_telemetry.py:395`, `:509`, `:614-624`; `lib/router_terminal.py:248` | not counted |
| Optional dashboard extras: OpenRouter balance probe, browser server, HTML renderer | monitoring weight (TEL-09 context; unverified) | telemetry audit | about 900 code + 500 test (could move behind an option instead) |
| Grafana dashboard cut from 68 panels to about 15; VM telemetry cut to about 10 counters plus one histogram | TEL-09 (unverified) | `grafana/subagent-model-router.json` (3,463 lines) | not estimated |
| Legacy tier eval | TEL-17 (unverified) | `eval/run.py` | 131, plus its case file and README |
| **Total** | | | **about 3,200–3,400 lines**, of which about 1,400 are the optional dashboard extras |

There is also a conditional candidate. Once the eval picks a winner, one of the two decision mechanisms can go:
either the factor policy (`lib/router_factors.py`, 278 lines, plus about 60 lines in `bin` and 273 test lines),
or the direct Choice path.

Keep these as they are:

- hook core:
  - the bounded single request with at most one retry;
  - fail-open hooks;
  - strict response validation;
  - the explicit, fork and override skips;
  - native catalogs as the only option source;
  - redaction and the oversize reject;
  - the exclude list, checked before any key or network use;
  - Codex-only `allow`;
  - the no-redirect opener for Jev;
- telemetry:
  - provider-reported Jev cost;
  - the Jev latency histogram and error counters;
  - local JSONL as the default backend;
  - the honest caveats in the docs;
  - the sandboxed tests;
- support:
  - safe file handling;
  - price semantics: exact IDs, never invented;
  - bounded subprocesses;
  - the codex-trust checks and dry-run.

## 4. What we adopt from the previous research

The previous note compared two other open-source projects that also put Jev in front of agents. It also kept a
backlog. Its verdict still holds: neither project replaces this plugin's hook.

### 4.1 Verdicts on the backlog and ideas

| Item | Verdict | Reason |
|---|---|---|
| 1. Eval for the direct Choice | **adopt now** (P0), extended | It is the largest gap (TEL-03, gap A), and every active-mode decision depends on it. Carry over the method: label "does a stronger tier change the outcome", use a prompt-length baseline and a judge that sees answers in both orders, and verify the model that actually served each request. Corrected control: random allocation that matches the evaluated router's **selected-tier distribution** [P6], not "share-matched content-blind allocation". |
| 2. Provenance hashes (options, instruction plus policy) | **adopt now** (P0) | Only `state_sha256` exists (`bin:394`, `bin:1247`, `bin:1378`). Eval and stats need to tell catalog, price and prompt changes apart. Hash the sorted options (model, effort, purpose, price) and, separately, the instruction text plus the `[policy]` config; write both to the journal. Check VM label cardinality before adding a hash-prefix label. |
| 3. Strip harness noise from the text sent to Jev | **adopt later**, measure first | jev-router strips `<system-reminder>`, `<environment_context>` and `<current_datetime>`; its author reports that reminders blunt Jev's confidence [U]. Unverified benefit. Subagent prompts are written by the parent model. Counting the blocks needs journal access, which is personal data and needs consent. |
| 4. Confidence gate on the Choice | **adopt now** (P1) | Confidence is parsed (`bin:469`), but the choice is always applied (`bin:1389`). Gate on the probability of the option actually applied. Candidate low-confidence actions: leave the launch unchanged, take the factor-policy pick, or move to the next more capable option; measure how often each would fire. The threshold needs eval data. Reference points [U]: JevRouter `min_confidence` 0.55; jev-router never downgrades below 0.3. |
| 5. Cache switch cost in the price model | **drop** the parent-switch part; the rest goes to N7 (**adopt later**) | [C3] [V]: a fresh subagent's first request does not read the parent's cache, and the parent's cache is unaffected. jev-router's "about 11 turns to repay a cache write" applies only to main-session switching. |
| 6A. Two-stage Choice | **drop** | Two calls inside a 3 s budget double latency. |
| 6B. Choice over models plus a Score for effort | **adopt later**, only as an arm of item 1 | The option set is every (model, effort) pair: 4 Claude aliases × up to 5 efforts, and Codex grows with each release. Model and effort interact. The factor policy already maps effort to the nearest level. |
| 7a. Model request parsed from task text | **drop** | The parent can already pass `model` (Claude) or `model`/`reasoning_effort` (Codex), and the hook skips explicit values (`bin:1338` for Claude, `bin:1342` for Codex). Document that instead. |
| 7b. Keep the last N Jev request bodies | **drop** (opt-in at most) | They contain task text, which is personal data. This conflicts with the journal's privacy design. |
| 7c. Catalog `max_input_tokens` / `created_at` | **adopt later** `max_input_tokens` as a hard filter; **drop** `created_at` | Haiku 4.5 has 200K context, against 1M for the others [A2]. |
| 7d. Override record (`fallback.type/reason`) | **adopt later**, together with the item-4 gate | Only needed once options are filtered after Jev answers. Today there is only `override_source="model_catalog"` (`bin:1334`). |
| 7e. Decision cache | **drop** | Tasks rarely repeat verbatim, and JevRouter keeps its cache off by default. |
| Gap B. `bin` is 2,290 lines | **adopt later**, incrementally | Move the Jev client and option building to `lib/` while doing items 1, 2 and 4. |
| Gap C. Dead code | **adopt later** (P3 cleanup) | Confirmed and widened by CORE-18 and SUP-10. |
| Gap D. Stale docs and checks | **drop** the README:8 part; **adopt later** the `check --live` part | README:8 is accurate historical framing (CORE-17 verifier). The `check --live` Codex probe is unverified. |
| Use JevRouter as a library | **drop** | It would replace only our Jev client of about 150 lines. It lacks a hook, launch rewriting, effort, native catalogs, price-aware selection, metrics export and a model-routing eval. |
| Patch a jev-router fork so it can coexist with this plugin | **drop** | The project has been silent since 2026-09-19 and is broken on current Claude Code (state as of 2026-10-02 [U]). |
| Main-session model routing through a proxy | **adopt later at most**, gated | Hooks cannot set the main model, so a proxy is the only route. The previous note itself gated this on an eval showing that upgrades improve quality. jev-router's oracle ceiling is 4–8% savings [U]. Rough cost: 1–2 weeks for Claude, one more for Codex [U]. |

### 4.2 Facts carried over

**Comparison** (pinned commits: JevRouter `e11084c`; jev-router `38da6b8` on `main` and `c08aee1` on its
`benchmarking` branch; the links are in [§9](#9-sources)):

| | JevRouter | jev-router | subagent-model-router |
|---|---|---|---|
| Routes | tool/skill/MCP/subagent/model choice, when the agent asks | the main-session model, per user turn | subagent model and effort, per launch |
| Mechanism | Skill plus a CLAUDE.md/AGENTS.md rule; CLI/SDK/MCP | loopback proxy that rewrites `model` | PreToolUse hook on `Agent` / `spawn_agent` |
| Effort | no | strips or clamps only | chosen |
| Catalogs / prices | no / no | `/v1/models` ids / no | yes / yes |

**JevRouter** (TypeScript, MIT, 88/88 offline tests):

- It is "not a tool interception layer" and does not switch the host model.
- Its features that we already cover: an HTTPS-or-loopback endpoint check (ours: `_check_endpoint`,
  `bin:169-180`), Choice answer validation, the raw answer kept (the journal `answers`, with probabilities and
  confidence), a state hash (`state_sha256`), and several questions in one request (the 8 factor questions next
  to the Choice).
- Its README benchmark measures tool choice only: 38–44% position hits on Toolathlon, against 24% for DeepSeek
  V4.1 Flash, at about 1/7 of the cost [U].
- Our answer validation (`bin:428-479`) is stricter:
  - the probabilities must cover exactly the offered options;
  - they must sum to 1 ± 0.02;
  - the choice must be a max-probability option;
  - unexpected keys are rejected.

**jev-router** (npm 0.3.0, MIT, about 1.5k LOC, 65/65 tests).

How it routes:

- It makes one Jev call per new user turn, with a 3 s budget (1.5 s × 2 attempts).
- Jev sees only the latest user text, the current model, a token estimate and the model ids. It gets three Score
  questions plus a Choice.
- Its policy:
  - keep the current model on any Jev failure;
  - below confidence 0.3, never downgrade, and cap upgrades at sonnet;
  - never downgrade past 20k context tokens.

Its own evidence is negative. These numbers are second-hand [U]:

- agentic eval (87 tasks, $59): AUC 0.570 [0.429, 0.693], against 0.613 for a prompt-length baseline;
- RouterBench: 0.591, against 0.597 for random routing at the same escalation rate;
- Jev proposed Haiku 31 times, and the shipped policy took it 0 times;
- a perfect oracle saves only 4–8%;
- cache economics: a first request is at least about 37k tokens, and a Haiku cache write costs 6× a Sonnet
  cache read. A downgrade therefore needs about 11 turns to pay back, while sessions average 4–6.

State on 2026-10-02 [U]:

- 48 commits in 3 days, then silence;
- 22 open issues and 13 open PRs;
- broken on current Claude Code: issues #58/#48 (fix in PR #36), #59 and #35.

Coexisting with this plugin works mechanically, but three conflicts remain:

- each routed subagent flips the main session to "manual";
- when our hook fails open, jev-router routes the subagent with its own policy;
- one launch can cost two Jev calls.

**Main-turn routing.**

- `UserPromptSubmit` only adds context, and `PreModelSwitch` only allows or blocks a switch.
- Claude Code 2.1.273 and later has `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`. It sends `x-claude-code-request-class`,
  `x-claude-code-agent-id` and `x-claude-code-prompt-id`, which would replace body sniffing [U: the fact-check did
  not cover it].

**Patterns not to copy:**

- long fixed timeouts (15–20 s);
- unauthenticated loopback endpoints;
- passing env or `.env` secrets to child processes;
- plaintext prompts in decision records by default;
- relying on CLAUDE.md/AGENTS.md for the agent to decide to route;
- body sniffing of undocumented wire formats;
- defaulting to the most expensive tier on failure;
- silent writes outside the project.

**Deliberately not carried over.** The rest of the previous note's jev-router internals (turn detection,
tool-loop pinning, unrouted auxiliary calls, behaviour after `--resume`, per-process status files, its list of
other defects) and its observability, eval and state comparison rows. They describe another project and change
no decision here. The full note remains in git history at commit `8d64156`
(`subagent-model-router/docs/jev-routers-research.md`).

**Fact-check correction.** The [P6] abstract says: "Fixed-tier baselines and selected-tier distributions are
therefore necessary controls in router evaluation." "Share-matched content-blind allocation" is only one
router's comparison point. Every eval arm in this report cites the correct pairing.

## 5. Optimal subagent model and run strategy

The goal is cheaper and faster subagent runs at the same quality.

### 5.1 Evidence classes

- **Measured here:**
  - Jev latency: median 0.40–0.60 s, p90 0.72 s, max 0.90 s.
  - Jev cost: about $0.000026–0.000043 per request.
  - Hook overhead: about 55–80 ms.
  - Request sizes.
  - Factor-policy accuracy: in-sample, 46 cases.
  - Nothing at all about subagent outcomes or subagent cost.
- **Vendor priors [V]:**
  - Anthropic's cost and intelligence guide [A5];
  - the OpenAI model-selection ladder [O8];
  - the Codex subagent guidance [O2] [O3].

  These come from vendor benchmark subsets. They are priors to validate, not guaranteed savings.
- **Literature [V]:** [P6] (routers emit constant tiers; Always-Mid matches), [P7] (a Bayes-error floor for
  text-only routing; cheap-first then escalate), [P8] (listed price often reverses), [P11] (the light tier pays
  off only when its pass rate exceeds the inter-tier cost ratio).
- **Hypotheses [U]:** everything below that is marked [U].

### 5.2 Static defaults plus escalation versus per-call Jev routing

- **Measured:** the Jev call is cheap, and its decision value is unknown (TEL-03). At [A1] prices even a
  10k/1k-token Haiku run costs $0.015, about 350× an eval-size Jev call (about 75–100× the production-size
  estimate [U]); real subagent runs cost cents to dollars [U]. The cost of a wrong decision therefore dwarfs the
  cost of the call.
- **Priors [V]:**
  - [A5]: "a multi-model configuration that looked cheaper than the default single model cost more than that same
    model at lower effort".
  - [A5]: Opus 5.5 at `low`, re-running the 13% of failures at `high`, reached about 97% at about $0.17 per task,
    against 95.3% at $0.29 for all-`high`. That is −41%, "for the saving, not the lift".
  - [P6]: "Always-Mid matches Aurelio exactly on three benchmarks". [P7]: execution feedback, not task text,
    carries the routing signal.
- **Recommendation [U]:**
  - Make the default path static per-client defaults (arm A1) plus escalation on an observed failure (arm A2).
    Neither needs a Jev call.
  - Keep the Jev Choice and the factor policy in shadow, sampled, until one of them passes the promotion rule in
    [§6.3](#63-promotion-rule).
  - If neither passes, ship A1/A2.
  - Removing Jev from the critical path also saves 0.4–0.6 s per spawn at eval request size (an estimated
    0.6–1.0 s at production size [U]), and up to 3 s when Jev hangs.
- **Open design point [U].** The inputs do not define how the hook observes a failure. The research proposes
  "raise one step when the parent re-launches after a failed check". The mechanisms available today:
  - the parent passes an explicit `model`, which the hook respects (`bin:1338` for Claude, `bin:1342` for Codex);
  - the parent picks an effort agent directly, which runs unrouted at that effort (CORE-11).

### 5.3 Per-client defaults

| Role | Claude Code | Codex | Basis |
|---|---|---|---|
| Default execution (`general-purpose`; Codex `default`/`worker`) | `opus` (Opus 5.5) at `medium` | `gpt-6.1-sol` at `medium` | [A5] "start with Claude Opus 5.5 at its default effort (`medium`)"; [O3] "start with `gpt-6.1-sol`"; 6.1-sol defaults to `medium` [V] |
| First escalation, after a failed check | Opus 5.5 at `high` | `gpt-6.1-sol` at `xhigh` | [A5] re-run at `high`; [O8] ladder [V]; exact step [U] |
| Second escalation, or demanding reasoning | `fable` (Fable 5.1) | `gpt-6-astra` | [A5] "use Claude Fable 5.1 for demanding reasoning … or when your evals on Claude Opus 5.5 at higher effort still fall short"; [O8] ladder [V] |
| Narrow, checkable, high-volume | `haiku`, only for verified, low-impact tasks (N5) | `gpt-6-luna` (`low`, up to `high`) | [C6] "For simple subagent tasks, specify `model: haiku`"; [O3] luna "for lighter subagent work"; the gate [U] |
| Read-only exploration | built-in Explore (not routed; it inherits the main model capped at Opus and skips CLAUDE.md) | built-in `explorer` on `gpt-6-luna` at `high`, read-only | [C1]; [O3] vendor example [V] |
| Review | Opus 5.5 at `medium`, escalating effort [U] | `gpt-6.1-sol` at `medium` | [O3] vendor reviewer example [V]; Claude side [U] |
| Not offered by default | `max` effort [U] | `ultra`, `max` (N2) | [O2] "Ultra uses subagents"; [A5] `xhigh` costs 2.5× for +1.4 points |

The `medium` start is the vendor prior [A5] [O3]. [A5]'s cheapest cascade starts at `low` instead, so A1-sweep
and the two A2 variants in [§6.2](#62-metric-and-arms) decide between a `low` and a `medium` start [U].

Per-token price effects [V] [A1] [O1]:

- Opus 5.5 ($4 / $20) against Fable 5.1 ($10 / $50) is 60% lower. [A5] reports the same pass rate (92.8% vs 92.3%)
  at about 1/5 of the cost per solved task ($0.22 vs $1.19).
- `gpt-6.1-sol` ($2 / $10) against `gpt-6-astra` ($10 / $50) is 80% lower, with "near-Astra performance" [O2].

**Codex rank fixes (N1).**

- Put `gpt-6.1-sol` at rank 3 in place of `gpt-6-sol`. The two cost the same, and 6.1-sol has the cheaper cache
  read ($0.10 vs $0.20).
- Drop these from the default table:
  - `gpt-5.4`: retired for ChatGPT sign-in on 2026-08-31;
  - `gpt-5.5`: leaves Codex on 2026-10-14;
  - `gpt-5.3-codex`: deprecated;
  - `gpt-5.6-luna`: dominated by `gpt-6-luna` at $0.10/$0.50;
  - `gpt-5.6-terra` and `gpt-5.6-sol`: never picked while a rank-3 model at $2/$10 exists.
- Exclude `ultra` and `max` from both the Choice options and the policy clamp (N2).

**Zero-router levers [U].**

- Codex: `[agents] default_subagent_model = "gpt-6.1-sol"` and `default_subagent_reasoning_effort = "medium"`,
  plus a luna-based `explorer`. The settings exist [O3] [O4]. Treating them as the static default is a
  recommendation.
- Claude Code: `CLAUDE_CODE_SUBAGENT_MODEL` sets the model for subagents that have no per-call or frontmatter
  model [C1]. Using it as the static default is a recommendation.

### 5.4 Effort levers

- **Effort is the biggest and best-measured lever [V] [A5].**
  - On SWE-bench Pro, Opus 5.5 relative to `high`: `medium` costs −2.5 points at about 70% of the cost; `low`
    costs −8 points at about 1/3; `xhigh` gains +1.4 points at 2.5×.
  - Research benchmarks are nearly flat: `low` gives up 1–3 points for 1/3–1/2 off.
- **Effort labels are not comparable across models [V] [O2] [C2].** A single Choice over (model, effort) pairs
  mixes incomparable labels. Sweep effort per model instead of ranking pairs globally.
- **Defaults differ by layer [V].** On the bare API, Sonnet 5.5 defaults to `high`; in Claude Code, Opus 5.5 and
  Sonnet 5.5 default to `medium`. Haiku 4.5 has no effort.
- **Caching across effort changes [V] [C3].** Opus 5.5, Sonnet 5.5 and Fable 5.1 keep the cache across effort
  changes; most other models have one cache per effort. On OpenAI, the model and the effort both affect the
  cached prefix [O7].
- **Overrides.**
  - `CLAUDE_CODE_EFFORT_LEVEL` makes the hook skip, so N4 is refuted.
  - `maxEffortLevel` still caps the effort silently. Record intended against effective effort.
- **Output and budget levers [V] [A5].**
  - A one-line output contract cost 2.8× less than a memo, at the same score. Put it in delegation packets.
  - Task budgets cut cost 44% for about 3 points, and 58% for 6 points. They are API-only, not a per-subagent
    lever in Claude Code.
  - `max_tokens` is not a cost lever.
- **`maxTurns` on routed agents as tail insurance [U].** On WideSearch, 2 of 20 problems carried 43% of the spend
  [A5]. Whether a cap helps needs the eval.

### 5.5 The CORE-01 prompt replacement and its quality confound

What is known:

- An effort agent's body replaces the Claude Code system prompt [C1] [V]. The built-in general-purpose prompt's
  content is undocumented, so the quality effect is unmeasured.
- Haiku launches keep `general-purpose` (no effort support, `bin:1047-1048`), and every other routed launch gets
  the two-sentence body. Any comparison of light against strong tiers in the current design therefore measures
  model and prompt together.

Recommended handling:

1. When the target effort equals the effort the launch would get anyway, rewrite only `model` and keep
   `general-purpose`. That holds for Opus 5.5 and Sonnet 5.5 at `medium` in Claude Code, but only if the session
   effort is the default. Without frontmatter, the subagent's effort comes from the session level [U, inferred
   from C2], so record the effective effort.
2. When the effort must differ, use the effort agent and record `prompt_variant` in the decision record.
3. Run the N3 arm: built-in `general-purpose` plus `model`, against `effort-<level>` at the same model and
   effort. Enrich the agent bodies only if the built-in prompt wins.
4. Within any eval arm, every launch must use the same prompt variant, whatever the model.

### 5.6 Fork versus fresh minimal context

- **Facts [V] [C3]:**
  - A fresh subagent's first request does not read the parent's cache, and the parent's cache is unaffected.
  - A fork reads the parent's cache.
  - Subagents use a 5-minute TTL by default.
  - Each fresh subagent pays its own cache write, at 1.25× input [A1].
  - The hook skips forks (the Keep list), so a fork runs unrouted on the parent's model.
- **Recommendation [U]:**
  - Make a fresh, minimal context the default. It is the routed path, and there is no parent cache to lose.
  - Use a fork only when the needed context cannot be serialized without losing meaning. Accept that the fork
    then runs on the parent's model, which may be the most expensive one.
  - Prefer fewer, larger subagents to a wide fan-out, because each fresh subagent pays its own cache write.
  - For narrow agents, `omitClaudeMd` and a minimal tool set shrink the prefix [C1]. The value is unmeasured.

### 5.7 Review versus execution

- **Current design:**
  - Review tasks ignore price and prefer a more capable model (README:27-32).
  - The factor policy adds `review` and `review_depth` factors. Both scored 1.00 on n = 12, in-sample.
- **Execution with checkable output:** go cheap first (lower effort, or the light tier when the gate allows it),
  then escalate on a failed check. [A5] supports this as a prior. [P11] gives a quick viability test: the light
  tier pays off only if its pass rate exceeds the inter-tier cost ratio. Derived from the [A1] and [O1] list prices
  (not measured), that ratio is about 0.25 for Haiku against Opus 5.5, and about 0.05 for luna against 6.1-sol. [P8] warns that listed prices can reverse
  in practice.
- **Review [U]:**
  - A review has no automatic check to escalate on, so cheap-first is riskier there.
  - Start at the default strong tier (Opus 5.5 or `gpt-6.1-sol`, both at `medium`), as in the vendor reviewer
    example [O3].
  - Raise effort for substantive reviews rather than jumping to the frontier model by default.
  - Measure review as a separate stratum.

### 5.8 What Jev should and should not decide

**Should** (in shadow until it is proven):

- Atomic task factors that code cannot get on its own: scope, error impact, how a wrong result would be caught,
  and whether the task is a substantive review.
- In-sample accuracy so far:
  - scope .815;
  - reasoning .761;
  - spec .717;
  - impact .696;
  - verification .674;
  - review 1.00 (n = 12).

**Should not:**

- Concrete cross-model effort labels, because labels do not map across models.
- Cost arithmetic. Code owns the prices. If the Choice stays, send only compact per-model rates (CORE-04, SUP-18).
- `ultra`/`max` (N2).
- `prior_failure` judged from text. Use an observed failure instead (N6).
- Low-confidence choices, which need the gate from backlog item 4.
- Anything at all while the endpoint hangs. That needs the circuit breaker (CORE-02).

## 6. Measurement plan

### 6.1 Telemetry fixes needed first

1. **Provenance in every decision record** (backlog item 2): an options hash, an instruction-plus-policy hash,
   `prompt_variant` (CORE-01), and intended against effective effort (N4 residual).
2. **A per-launch cost and outcome join** (N8):
   - Claude OTel `claude_code.cost.usage` and `claude_code.token.usage`, filtered to subagent `query_source` and
     keyed by `agent_id`/`parent_agent_id` [C5];
   - SubagentStop for completion;
   - Codex `multi_agent.spawn{role}` [O5].

   Analysing the user's own journal and telemetry needs their explicit consent.
3. **`hook_ms` in the local journal** (TEL-07).
4. **No silent loss of cost data** on the VM backend (TEL-02), and a working calls query (TEL-01). TEL-04 is low
   after verification (a realistic payload is about 1.15 MB, under the 2 MiB cap), so its fix can follow in P2.
5. **Per-model price status** in the decision record and in `check` (SUP-01, SUP-05). Otherwise cost keys silently
   fall back to rank.
6. **In shadow, the static A1 decision written next to the Jev decision**, so that disagreement rates can be
   counted.

### 6.2 Metric and arms

**Primary metric: cost per solved task (cost-of-pass [P5]).** It is list-price cost, computed from the five token
counts (input, 5-minute write, 1-hour write, cache read, output), divided by the number of tasks that pass their
stated check. Also report:

- pass rate;
- p50 and p90 wall time;
- escalation (re-launch) rate;
- the share of spend in the top 10% of tasks [A5].

**Offline set:** 100–200 frozen, real delegation packets with automated checks. Drawing them from the user's
sessions needs consent. Run them paired: every task through every arm, with 2 repeats, because thinking tokens vary
up to 9.7× between runs [P8].

| Arm | What it runs | Role |
|---|---|---|
| A0 | no routing (inherit) | today's no-plugin baseline |
| F-light / F-mid / F-frontier | fixed tier for every task (F-mid equals A1) | fixed-tier baselines [P6] [A5] |
| A1-sweep | the A1 model at `low`, `medium` and `high` | effort sweep; the curve to beat [A5] |
| A2 | A1 escalating one step along the [§5.3](#53-per-client-defaults) ladder on a failed check, in two variants: started at `medium` (A2-mid, the recommended default) and at `low` (A2-low, [A5]'s low-then-`high` cascade) | cascade [A5] [P7] |
| A3 | factor policy | candidate |
| A4 | Jev direct Choice | candidate |
| C1 | random allocation matching A4's selected-tier distribution | content-blind control [P6] |
| C2 | prompt-length rule | free baseline (jev-router's 0.613 AUC [U]) |
| N3 | built-in `general-purpose` + `model`, against `effort-<level>` at the same model and effort | CORE-01 prompt control |

Ordering, following [A5]'s method [V]: run the fixed tiers, the sweep and A2 first. Add the multi-model arms (A3,
A4, C1, C2) only if a gap remains. Without a gap, Jev has nothing to win.

### 6.3 Promotion rule

Promote an arm over A1/A2 only if both conditions hold, measured paired:

- its cost-of-pass is **at least about 15% lower** than the best point on A1-sweep;
- its pass rate is **non-inferior within 2–3 points**.

Otherwise ship A1/A2, and keep Jev in shadow or turn it off.

### 6.4 Sample sizes

- **Offline:** 100–200 paired tasks × 2 repeats, as estimated by the research. The inputs contain no paired power
  calculation. For scale: the current factor eval, 46/46 correct, gives a Wilson 95% lower bound of only about 92%.
  A set that small cannot establish a non-inferiority margin of 2–3 points.
- **Online, unpaired:** about 2,400 tasks per arm to detect a 3-point drop from 85% (α 0.05, power 0.8). Use online
  only to confirm offline results. The path:
  1. shadow, with the A1 decision in the same record;
  2. then a session-hash traffic slice.
- **Re-check triggers:** re-run A1-sweep on every model or price change:
  - Haiku 4.5 retirement (on or after 2026-10-15);
  - `gpt-5.5` leaving Codex (2026-10-14);
  - the end of the GPT-5.6 Sol promotional pricing (on or after 2026-11-21).

  The provenance hash makes the before/after split explicit.

## 7. Prioritized roadmap

The full checklist, with files and acceptance criteria, is [TODO.md](../TODO.md).

- **P0, measurement foundation and the high bug:**
  - provenance and prompt-variant recording;
  - the OTel cost and outcome join;
  - a frozen task set and the paired strategy eval;
  - a static-plus-escalation mode;
  - the CORE-01 prompt fix with the N3 arm;
  - factor questions off by default.
- **P1, correctness of defaults and of the data:**
  - Codex ranks;
  - excluding `ultra`/`max`;
  - the Haiku gate;
  - the confidence gate;
  - price status and parser robustness;
  - no whole-event drops at the VM series cap, fewer series per event, and the calls query;
  - `hook_ms`;
  - measuring the production request;
  - a held-out factor set;
  - a documentation pass;
  - the synchronous `codex plugin list`;
  - re-check triggers.
- **P2, hook-path cost and policy quality:**
  - the circuit breaker;
  - a true `enabled = false`;
  - start-up cost;
  - redundant per-call work;
  - Choice payload trim;
  - the blended cost key;
  - the policy effort floor;
  - refresh rate limits;
  - delivery-failure reporting.
- **P3, cleanup:**
  - dead code;
  - walkers and caches;
  - directory permissions;
  - catalog consistency;
  - small semantics fixes;
  - shadow sampling;
  - Grafana;
  - local stats;
  - the legacy eval;
  - optional dashboard extras;
  - removing the losing decision mechanism, once the eval picks a winner;
  - splitting `bin`;
  - `max_input_tokens`;
  - measuring harness noise.

## 8. Measurements appendix

### 8.1 Hook timings

Core audit (sandboxed, medians):

| Path | ms |
|---|---|
| Bare interpreter | 13.6 |
| Compiling `bin` | 14.4 |
| `router_telemetry` import | 11.8–17.5 |
| Non-agent hook | 57.7 |
| Matcher false positive | 61.7 |
| `enabled = false` | 63.6 |
| Routed, instant fake Jev | 80.8 (74–92; the Jev leg is 14–18 on loopback) |

Core verifier (8 runs, medians):

| Path | ms |
|---|---|
| `python3 -S` | 7.0 |
| `python3` | 13.8 |
| Non-agent Read | 55.1 |
| `mcp__x__AgentSearch` | 55.0 |
| Agent, no config | 52.9 |
| No bytecode cache | 60.6 |
| `router_telemetry` import | 11.6 |
| `urllib.request` import | 6.7 |
| Compiling `bin` | 11.6 |

Support audit (21 runs each, median/p90 in ms):

| Command | No config | `enabled = false` | Enabled |
|---|---|---|---|
| `python3 -c pass` | 13.8/14.5 | | |
| update-notice | 55.3/65.8 | 59.2/67.2 | 58.8/71.9 |
| telemetry-kick | 53.8/63.6 | 52.6/69.8 | 56.6/71.2 |
| claude-session | 67.0/77.4 | 61.6/72.0 | 64.1/69.2 |
| claude-session under a fake Claude | | | 66.2/73.3 |
| Codex update-notice (cached/uncached) | | | 54.7/56.5 |

The support verifier measured update-notice with no config at 61.4 ms, against 13.5 ms for bare `python3`.
Compiling `bin` took 30.8 ms, the `router_telemetry` import 25.3 ms, and `tomllib` 8.6 ms.

**Per prompt:** 2 Python processes, 1 fsync and 1 `/proc` walk; about 55–60 ms synchronous and about 110 ms CPU.
Under Codex, add up to 1 s for `codex plugin list` on a cache miss (SUPV-N1).

**Per SessionStart:** 3 processes and 1 `--version` probe, plus a detached refresh worker and a headless client
start; about 65 ms synchronous and about 190 ms CPU. 155–162 modules are imported, and the hook's own logic takes
under 1 ms.

**Jev round trip:**

- from the eval data: median 0.40–0.60 s, p90 0.72 s, max 0.90 s;
- estimated at production request size: 0.6–1.0 s [U];
- timeout case 3.07 s; a 503 followed by a retry 2.09 s;
- worst case about 8.1 s, inside the 10 s hook timeout.

A typical routed launch adds about 0.7–1.1 s (an estimate [U]: about 0.08 s local plus the estimated 0.6–1.0 s
production-size Jev call); 3.1 s when Jev hangs (measured).

**I/O per routed call:**

- the config TOML, read twice;
- the catalog cache, read once;
- the price cache, read twice;
- up to 17 effort-definition reads;
- the client-version flock;
- one journal append or sqlite enqueue (enqueue: 2.59 ms mean, 3.38 ms p95, 9.48 ms max);
- one POST, plus at most one retry on 429/5xx.

### 8.2 Request sizes (bytes)

| Part | Claude default | Claude, policy off | Codex |
|---|---|---|---|
| Compact body | 11,394 | 9,115 | 8,975 |
| Wire body | 11,706 | 9,357 | 9,353 |
| `state` | 274 | 274 | 326 |
| Instructions | 5,791 | 5,791 | 4,575 |
| – fixed prefix | 2,425 | 2,425 | 2,424 |
| – estimate | 318 | 318 | 319 |
| – shared context | 3,048 | 3,048 | 1,832 |
| Criteria (count / B) | 16 / 2,645 | 16 / 2,645 | 15 / 1,482 |
| Factor questions (count / B) | 8 / 2,280 | 0 | 8 / 2,280 |
| Tokens at bytes/4 | ~2,780 | ~2,211 | ~2,163 |
| Likely billed tokens | 3.3–4.2K | 2.7–3.3K | 2.6–3.3K |

Fixed text makes up 96–97% of the request. The verifier's fixture gave Claude 10,776 B against 8,497 B (+26.8%) and
Codex 8,464 B against 6,185 B (+36.8%).

### 8.3 Test suite

- `python3 -B tests/run_parallel.py -j 4` (sandboxed): 453 tests in 38 classes, all OK, in 27.2 s (27.4 s wall).
  No skips, no network.
- Slowest classes: Catalog 13.5 s, Skip 12.5 s, Failure 10.3 s.
- 57 tests cover code that nothing in production calls.
- No test covers SUP-04, SUP-12, SUP-13, SUP-14 or TEL-04.

### 8.4 Eval numbers

**Tier classifier, 2026-09-25** (from before 0.5; `eval/results-20260925*`):

- 28 cases × 2 input variants × 2 repeats = 112 requests, 0 failures.
- Final route correct: 48/56 (85.7%) for both variants.
- Under-routing 4 (S03, S04); over-routing 4 (C05, L07).
- Risk false positives 10/44 and 12/44; false negatives 0.
- By expected route: heavy 26/26, light 16/16, standard 6/14.
- By language: ru 22/26, en 26/30.
- Latency: mean 417 ms, p50 399, p95 485, max 861.
- Cost: $2.60e-5 to $2.85e-5 per request; $0.00306 in total.

**Factor policy, 2026-09-27** (`eval/factors_results-20260927*`):

- 46 cases (23 EN, 23 RU) × 2 = 92 requests, 0 failures.

| Metric | Pre-fix | Post-fix |
|---|---|---|
| Within band | 95.65% | 100% |
| Under-routing | 4.35% (P02, P04: 4→3) | 0 |
| Exactly at band minimum | 80/92 | 80/92 |
| One step above minimum | 8 | 12 |

- Level mix L1–L4: 28/20/24/20, against an expected 36/12/28/16.
- Confusion: 1→2 ×8 (X01, X02, E01, E03); 3→4 ×4 (P01, P03).
- Repeat disagreement 0; pair discrimination 128/144.
- Adjustments: confidence_raise 39, impact_floor 24, verified_discount 16, review_floor 8, frontier_scope 8,
  prior_failure_raise 8.
- 74 of 92 runs have a disagreeing factor, yet 68 of them land at the band minimum. Without the confidence raise:
  5 under-routed, 83 exact.
- Latency: mean 613 ms, p50 598, p90 718, p95 750, max 902.
- Per request: 1,020 input and 129 output tokens, $4.28e-5; $0.003942 in total.
- Wilson 95% lower bound for 46/46: about 92%.

| Factor | Accuracy | Mean confidence | Confidence ≥ 0.6 | Main error |
|---|---|---|---|---|
| reasoning | .761 | .897 | 96% | too high ×22 |
| spec | .717 | .845 | 95% | too high ×26 |
| verification | .674 | .576 | 52% | too high ×30 |
| scope | .815 | .793 | 76% | too high ×15, too low ×2 |
| impact | .696 | .544 | 46% | too low ×18, too high ×10 |
| review / review_depth | 1.00 / 1.00 (n = 12) | – | – | – |
| prior_failure | .957 | – | – | 4 false positives (P01, P03) |

**Across both evals:** 204 requests and 0 failures.

The evals do not show:

- the Choice;
- `select()`;
- bands set independently of the labels;
- held-out generalization;
- subagent quality or cost;
- the production request shape;
- production timeout or skip rates.

## 9. Sources

All accessed 2026-10-02. The web fact-check re-confirmed:

- the [A1] and [O1] price tables, the Claude Code aliases and default efforts ([C2], [A2]);
- the [A5] figures quoted here: 92.8% at $0.22 against 92.3% at $1.19, 87.4% at $0.12 for `low`, "start with
  Claude Opus 5.5 at its default effort (`medium`)", the multi-model comparison, the low-then-`high` cascade
  (about 97% at $0.17 against 95.3% at $0.29), the 2.8× memo cost and the 44–58% task-budget cuts;
- [C1] (the body becomes the system prompt; plugin restrictions; model precedence), the [C2] effort precedence
  and `maxEffortLevel`, the [C3] non-fork cache behaviour and the [C4] `async_launched` payload;
- [O2] (GPT-5.5 leaves Codex on 2026-10-14; 6.1 Sol is near-Astra; "Ultra uses subagents") and [O3] (start
  with `gpt-6.1-sol`; luna for lighter subagent work; precedence);
- [P6] (constant tiers; Always-Mid), [P7] and [P8].

It found one wrong quote, the [P6] "necessary controls" pairing, corrected in [§4.2](#42-facts-carried-over). The
other `[V]` claims rest on the research audit's own reading of the source and were not re-checked: the [A5]
effort-sweep figures and WideSearch tail share, the [O8] ladder, the [O3] explorer and reviewer examples, the
Haiku 4.5 facts ([A2], [A4]), the Codex retirement, deprecation and promotion dates, the [C3] effort-cache
behaviour, [C6], [O7], and `gpt-6.1-sol` defaulting to `medium`.

- [A1] https://platform.claude.com/docs/en/about-claude/pricing
- [A2] https://platform.claude.com/docs/en/models/overview
- [A3] https://platform.claude.com/docs/en/build-with-claude/effort
- [A4] https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- [A5] https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence
- [C1] https://code.claude.com/docs/en/sub-agents
- [C2] https://code.claude.com/docs/en/model-config
- [C3] https://code.claude.com/docs/en/prompt-caching
- [C4] https://code.claude.com/docs/en/hooks (fetch the raw page; summarizing tools truncate it)
- [C5] https://code.claude.com/docs/en/monitoring-usage
- [C6] https://code.claude.com/docs/en/costs
- [C7] https://code.claude.com/docs/en/advisor
- [O1] https://developers.openai.com/api/docs/pricing
- [O2] https://developers.openai.com/codex/models (redirects to https://learn.chatgpt.com/docs/models)
- [O3] https://developers.openai.com/codex/subagents (redirects to https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [O4] https://developers.openai.com/codex/config-reference (redirects to https://learn.chatgpt.com/docs/config-file/config-reference)
- [O5] https://developers.openai.com/codex/config-advanced (redirects to https://learn.chatgpt.com/docs/config-file/config-advanced)
- [O6] https://developers.openai.com/api/docs/guides/reasoning
- [O7] https://developers.openai.com/api/docs/guides/prompt-caching
- [O8] https://developers.openai.com/api/docs/guides/model-selection
- [P1] RouteLLM: https://arxiv.org/abs/2406.18665
- [P2] FrugalGPT: https://arxiv.org/abs/2305.05176
- [P3] RouterBench: https://arxiv.org/abs/2403.12031
- [P4] Unified routing and cascading: https://arxiv.org/abs/2410.10347
- [P5] Cost-of-Pass: https://arxiv.org/abs/2504.13359
- [P6] Task- and Session-Level Model Routing: https://arxiv.org/abs/2608.14641
- [P7] SWE-Router: https://arxiv.org/abs/2607.00053
- [P8] Price Reversal: https://arxiv.org/abs/2603.23971
- [P9] TwinRouterBench: https://arxiv.org/abs/2605.18859
- [P10] Agent-as-a-Router: https://arxiv.org/abs/2606.22902
- [P11] Triage: https://arxiv.org/abs/2604.07494
- Not verifiable: https://openrouter.ai/typesafe/jev-1.13 returned 404, so Jev's public price is unconfirmed [U].
- Other Jev routers, pinned:
  - JevRouter: https://github.com/BillionsBobby/JevRouter/tree/e11084c808e1902d11230e7a7937e5008fec7f02
  - jev-router (`main`): https://github.com/gargpratyush/jev-router/tree/38da6b84ea01241bfc41fbddc0928d0f40a703f0
  - jev-router (`benchmarking`): https://github.com/gargpratyush/jev-router/tree/c08aee16595bcd510acbd134465acebb361c7085
