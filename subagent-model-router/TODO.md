# subagent-model-router: TODO

The backlog from the [2026-10 audit](docs/router-audit-2026-10.md).

- Each item names the finding ids or report sections it closes, the files to touch, and one acceptance check.
- Paths are relative to this directory, and `bin` means `bin/subagent-model-router`.
- Line numbers refer to version 0.6.1.
- Refuted and dropped findings (CORE-15, N4, SUP-15, SUP-17) are deliberately left out. Only the N4 residual
  (undetected `maxEffortLevel` and effort caps) remains: intended against effective effort is recorded under P0
  "Record decision provenance", and the `check` warning is under P3.
- Priority follows severity: high findings are P0, medium findings P1, low findings P2 or P3. Research items N3
  and N5–N8 carry benefit ratings rather than severities and follow the research audit's priority or higher. A low
  finding sits higher when the eval depends on it (CORE-03/TEL-05, TEL-06, TEL-07, TEL-11, CORE-17), when it shares
  a task or a failure with a higher one (SUP-01 and SUP-14 with SUP-05, SUP-09 with SUPV-N1, CORE-08 with N1, TEL-10
  with TEL-09), or when it is part of the one documentation pass.

## P0: do first

These lay the measurement foundation and fix the high-severity bug. Without them, no routing change can be shown to
be cheaper at the same quality.

Each P0 item is a task of the [P0 queue](queues/p0.toml), which task-panes runs ([queues/README.md](queues/README.md)).
The queue's `todo` field names the item by its exact bold title, so a title never changes once the queue refers to it.

- [ ] **Record decision provenance.**
  - Closes: [backlog item 2][s41], [CORE-01][s31] (prompt variant), [N4 residual][s31].
  - Files: `bin` (decision record near :1247 and :1378), `lib/router_telemetry.py`, tests.
  - Accept: every decision record carries an options hash, an instruction-plus-policy hash, `prompt_variant`, and
    intended and effective effort. A test shows that each hash changes when the catalog, the prices or the
    instructions change.
- [ ] **Join per-launch cost and outcome by `agent_id`.**
  - Closes: [N8][s33], [§6.1][s61].
  - Files: `bin` (record key), `lib/router_telemetry.py`, `skills/subagent-model-router/references/monitoring.md`,
    `eval/`.
  - Accept: given fixture OTel `cost.usage`/`token.usage` records and a decision journal, a test produces the cost
    and the completion state of each routed launch.
- [ ] **Build the paired strategy eval.**
  - Closes: [TEL-03][s33], [backlog item 1][s41], [N6][s33], [N3][s31], [§6.2][s62].
  - Files: `eval/` (a new strategy runner and its README).
  - Accept: the runner executes arms A0, F-light/F-mid/F-frontier, A1-sweep, A2 (`medium` and `low` starts), A3,
    A4, C1, C2 and N3 on a fixture set with fake clients. Per arm it reports cost-of-pass, pass rate, p50/p90 wall
    time and escalation rate.
- [x] **Assemble the frozen task set, stage 1: 50 tasks in four domains.**
  - Closes: [§6.2][s62] (the set, in part).
  - Files: `eval/taskset/` (tasks, `MANIFEST.json`; `taskset.py` and its README when a public dataset joins).
  - Accept: `MANIFEST.json` lists at least 50 tasks that meet the stage-1 spread of
    [eval/taskset/README.md](eval/taskset/README.md#stages): `math`, `code`, `debug` and `text`, at least 8 each,
    difficulties 1–3 across the set, at least 10 tasks in Russian; every task reviewed by someone other than its
    author. `tests/test_taskset.py` passes. A task is written here or taken from a public dataset whose task and
    tests are reachable by direct links under a license that allows redistribution; such a task is vendored with its
    source pinned. Consent is recorded for any packet drawn from user sessions.
- [ ] **Add a static-default mode with escalation.**
  - Closes: [N6][s33], [§5.2][s52], [§6.1][s61] (item 6).
  - Files: `bin`, `config.example.toml`, `README.md`, tests.
  - Accept:
    - in static mode the fake Jev receives 0 requests, and each launch gets the configured per-client model and
      effort;
    - the escalation signal is chosen and documented (the [§5.2][s52] open design point), and a test shows that a
      launch carrying it gets the next configured step (for example `medium` to `high`);
    - in shadow mode the decision record carries the static A1 decision next to the Jev decision (test).
- [ ] **Remove the CORE-01 prompt asymmetry.**
  - Closes: [CORE-01][s31], [N3][s31], [§5.5][s55].
  - Files: `bin` (`apply_selection`, :1284-1291; :1047-1048), `agents/effort-*.md`, `README.md` (:36-42), tests.
  - Accept:
    - a test shows that haiku and non-haiku launches in one arm get the same prompt variant;
    - a launch whose target effort equals the effort it would get anyway is rewritten for `model` only.
- [ ] **Turn shadow factor questions off by default, or sample them.**
  - Closes: [CORE-03][s32], [TEL-05][s32].
  - Files: `lib/router_factors.py` (:70), `config.example.toml` (:25), `README.md` (:123), tests.
  - Accept: the default request carries 0 factor questions; a test asserts the body shrinks by about 2,280 B.
- [ ] **Debug the bench on the stage-1 set.**
  - Closes: [§6.2][s62] (first real run).
  - Files: `eval/` (the strategy runner, its README, a results directory), `eval/taskset/` (retirements only).
  - Accept:
    - the strategy runner runs the arms on every stage-1 task with real clients, one repeat, with the task set hidden
      from the subagents under test; a smaller smoke run comes first;
    - before any paid launch, the arms × tasks × repeats and the estimated cost are stated and the owner approves
      them;
    - every defect the run exposes is fixed: in the runner by a change with a test, in a task by retiring it;
    - the run's report (cost-of-pass, pass rate, p50/p90 wall time, escalation rate per arm, and the set hash) is
      committed.
- [ ] **Grow the frozen task set, stage 2: 190 tasks in all domains.**
  - Closes: [§6.2][s62], [§6.4][s64].
  - Files: `eval/taskset/`.
  - Accept: `MANIFEST.json` lists at least 190 tasks that meet the stage-2 spread (all eight domains, at least 20
    each, each domain covering difficulties 1–3, at least 19 in Russian); `tests/test_taskset.py` passes; merged
    tasks are unchanged.

## P1

These fix the defaults and the data the eval depends on.

- [ ] **Fix the Codex capability ranks.**
  - Closes: [N1][s31], [CORE-08][s31], [§5.3][s53].
  - Files: `lib/router_factors.py` (:74-78, :237, :248-255), `config.example.toml` (:43-45), tests.
  - Accept:
    - with the current OpenAI prices, a level-3 task picks `gpt-6.1-sol`;
    - `gpt-5.4`, `gpt-5.5`, `gpt-5.3-codex`, `gpt-5.6-luna`, `gpt-5.6-terra` and `gpt-5.6-sol` are absent from the
      default table.
- [ ] **Exclude `ultra` and `max` efforts.**
  - Closes: [N2][s31].
  - Files: `bin` (:706-715, :1066), `lib/router_factors.py` (`_effort_for`), tests.
  - Accept: with a catalog that offers `ultra`/`max`, neither the Choice options nor the policy clamp contain them
    by default (test).
- [ ] **Gate Haiku.**
  - Closes: [N5][s31].
  - Files: `lib/router_factors.py` (:75), `bin` (option building), `config.example.toml` (:36), tests.
  - Accept: `haiku` is offered only for verified, low-impact tasks (test). The eval reports its pass rate as a
    separate stratum.
- [ ] **Gate the Choice on confidence.**
  - Closes: [backlog items 4 and 7d][s41].
  - Files: `bin` (:469, :1389), `config.example.toml`, tests.
  - Accept: below the threshold the hook keeps the static default and records a `fallback` reason (test). The
    threshold value comes from the eval.
- [ ] **Report price status in `check` and retry with backoff.**
  - Closes: [SUP-01][s35].
  - Files: `lib/router_model_prices.py` (:267-280, :338-347), `bin` (:1775-1783), tests.
  - Accept: `check` prints the price status of each model and never says "ready" while prices are unknown, and the
    decision record carries the price status of each offered model. Retries follow 15 min / 1 h / 6 h (test).
- [ ] **Make the price parser robust.**
  - Closes: [SUP-05][s35], [SUP-14][s35].
  - Files: `lib/router_model_prices.py` (:26-30, :67-87, :154-169, :331), tests.
  - Accept: fixtures with renamed columns, a same-host HTTPS redirect and an `IncompleteRead` each end in valid
    prices or in a recorded `parse_failed`/error status, never an escaped exception.
- [ ] **Stop VM events from being dropped at the series cap.**
  - Closes: [TEL-02][s34].
  - Files: `lib/router_telemetry.py` (:33-34, :643-646), `skills/subagent-model-router/references/monitoring.md`,
    tests.
  - Accept: a test with 30 projects per agent still delivers the cost, latency and error counters, and no event is
    dropped whole.
- [ ] **Shrink VM telemetry.**
  - Closes: [TEL-09][s38], [TEL-10][s38].
  - Files: `lib/router_telemetry.py` (:395, :509, :614-624), `lib/router_terminal.py` (:248),
    `grafana/subagent-model-router.json`, tests.
  - Accept: a test shows the series per event falling from about 154 to about 10 counters plus one histogram, with
    no `rule:*` reasons and no tier label left.
- [ ] **Split the VM calls query.**
  - Closes: [TEL-01][s34].
  - Files: `lib/router_dashboard.py` (:21, :46-47, :264), tests.
  - Accept: a test with more than 120 series renders the main stats panels.
- [ ] **Record `hook_ms` in the local journal.**
  - Closes: [TEL-07][s34], [TEL-11][s32].
  - Files: `bin` (:1486-1493), `lib/router_dashboard.py` (:670), tests.
  - Accept: journal records carry `hook_ms` including enqueue time, and the Hook row in the local HTML is filled
    in (test).
- [ ] **Measure the production request shape.**
  - Closes: [TEL-05][s32], [TEL-03][s33], [CORE-17][s37].
  - Files: `eval/factors_run.py` (:329), `eval/factors_README.md` (:9), `README.md` (:104).
  - Accept: an eval run reports tokens and p50/p90 latency for the merged Choice-plus-factor request, and README:104
    states the measured numbers.
- [ ] **Add a held-out factor set and checked summaries.**
  - Closes: [TEL-06][s33].
  - Files: `eval/factors_run.py` (:370-381), `eval/` case files and results.
  - Accept: the held-out results are reported separately, and the runner fails when a stored summary does not match
    its data.
- [ ] **Fix documentation drift.**
  - Closes: [SUP-18][s37], [CORE-17][s37], [CORE-12][s31], [CORE-05][s36], [SUP-02][s36], [SUP-19][s37],
    [TEL-14][s33].
  - Files:
    - `README.md` (:104, :113-114, :236, :304-307);
    - `config.example.toml` (:22);
    - `skills/subagent-model-router/SKILL.md` (:122, :162);
    - `lib/router_factors.py` (:1-7).
  - Accept: a test asserts that "Prices never reach Jev" is gone, and that README:236 matches what
    `enabled = false` actually does.
- [ ] **Move `codex plugin list` off the prompt path.**
  - Closes: [SUPV-N1][s32], [SUP-09][s32].
  - Files: `lib/router_update_notice.py` (:146, :236, :260-266, :277-286), tests.
  - Accept: under a fake `codex` that sleeps 1 s, the update-notice hook median stays under 100 ms after a cwd
    change (baseline about 55–60 ms; the synchronous probe adds about 1 s), and no fsync happens per prompt (test
    or benchmark).
- [ ] **Re-run the effort sweep on model and price changes.**
  - Closes: [§6.4][s64].
  - Files: `eval/` (results).
  - Accept: an A1-sweep result split by provenance hash exists after each of these events:
    - Haiku 4.5 retirement (on or after 2026-10-15);
    - `gpt-5.5` leaving Codex (2026-10-14);
    - the end of the GPT-5.6 Sol promotional pricing (on or after 2026-11-21).

## P2

Hook-path cost and policy quality.

- [ ] **Add a Jev circuit breaker and shorten the timeout.**
  - Closes: [CORE-02][s32].
  - Files: `bin` (:258-260, :507-571, :1380-1393), `config.example.toml` (:12), tests.
  - Accept:
    - with a hung fake Jev, the next hook within about 120 s returns in under 100 ms;
    - a test asserts the new default timeout, set above the production-size p90 from "Measure the production
      request shape" (the audit suggests about 1.5 s; the 0.72 s eval p90 comes from smaller requests).
- [ ] **Make `enabled = false` a true early exit.**
  - Closes: [CORE-05][s36], [SUP-02][s36].
  - Files: `bin` (:1327, :1370-1371, :1478-1487, :1516-1520, :1558-1559), tests.
  - Accept: a test shows that with `enabled = false` no journal record, no subprocess and no notice is produced.
- [ ] **Cut hook start-up cost.**
  - Closes: [CORE-07][s32], [SUP-07][s32].
  - Files: `bin` (:22, :288, :336), `hooks/hooks.json` (:5, :15), a new thin launcher.
  - Accept: in the sandboxed benchmark, the non-agent hook median falls from 55 ms to 35 ms or less. The target is
    derived from the estimated −20 ms of a thin launcher.
- [ ] **Remove redundant per-call work and write stdout first.**
  - Closes: [CORE-13][s32], [CORE-14][s32], [TEL-11][s32].
  - Files: `bin` (:1014-1026, :1351, :1463-1499, :1481), `lib/router_model_prices.py` (:248, :344), tests.
  - Accept: per routed call, a test counts 1 config load, 1 price parse and at most 1 effort-definition read, and
    the decision is written to stdout before the journal.
- [ ] **Trim the Choice payload.**
  - Closes: [CORE-04][s32], [SUP-18][s37].
  - Files: `bin` (:1120-1175), `lib/router_token_budget.py`, tests.
  - Accept:
    - `visible_task` and the per-task USD estimate are gone;
    - price entries are `{input, output, status}`;
    - the wire body equals the compact body (`ensure_ascii=False`);
    - the size reduction is asserted in a test.
- [ ] **Use a blended cost key in the policy.**
  - Closes: [CORE-08][s31], [N7][s35].
  - Files: `lib/router_factors.py` (:214-217, :248-255), tests.
  - Accept: a test with OpenAI-like 5–8× input/output ratios selects by the blended rate. The eval compares
    cost-of-pass against the output-only key.
- [ ] **Add a policy effort floor and harden parsing.**
  - Closes: [CORE-06][s31], [CORE-12][s31].
  - Files: `lib/router_factors.py` (:150, :178-209, :220-229), tests.
  - Accept: tests show that a level-4 pick never launches at `low`, and that an effort label outside
    `EFFORT_ORDER` is rejected.
- [ ] **Rate-limit catalog refreshes.**
  - Closes: [CORE-16][s35], [SUP-03][s35].
  - Files: `bin` (:829, :864-936, :984-992, :1523-1525), `lib/router_claude_catalog.py` (:314-315),
    `hooks/hooks.json` (:15), tests.
  - Accept:
    - with a failing Codex catalog, 20 spawns within 10 minutes start at most 1 refresh;
    - SessionStart no longer forces a refresh (test).
- [ ] **Surface telemetry delivery failures.**
  - Closes: [TEL-04][s34], [TEL-16][s34].
  - Files: `lib/router_telemetry.py` (:360, :665-666, :750-752, :763, :811-813), `bin` (:1494-1495), tests.
  - Accept: tests show that an oversized payload sets `last_error` and is split, and that an enqueue failure
    increments a counter.

## P3: cleanup

- [ ] **Delete dead and test-only code.**
  - Closes: [CORE-18][s38], [SUP-10][s38], [gap C][s41].
  - Files:
    - `bin` (:37);
    - `lib/router_runtime.py`;
    - `lib/router_claude_model.py`;
    - `lib/router_claude_state.py` (:29-69, :117-141, :144-263);
    - their tests.
  - Accept: the suite passes, with about 1,150–1,300 lines removed, tests included.
- [ ] **Merge the `/proc` walkers and simplify the version and notice caches.**
  - Closes: [SUP-11][s38], [SUP-06][s36], [SUP-08][s36].
  - Files:
    - `bin` (:120-141, :591-604, :632-646);
    - `lib/router_client_version.py`;
    - `lib/router_update_notice.py` (:25, :237, :253-256);
    - tests.
  - Accept:
    - one walker remains;
    - a 200-session test loses no notice and no version record to slot collisions.
- [ ] **Apply one directory-permission policy and honour TMPDIR.**
  - Closes: [SUP-04][s36], [SUPV-N2][s36], [SUP-16][s36].
  - Files:
    - `bin` (:309, :757-763);
    - `lib/router_claude_state.py` (:91-99);
    - `lib/router_update_notice.py` (:198);
    - `lib/router_claude_catalog.py` (:104);
    - tests.
  - Accept: tests show that `check` flags a 0755 config dir and a group-writable parent, and that the catalog temp
    dir follows TMPDIR.
- [ ] **Make catalog descriptions consistent and tolerant.**
  - Closes: [SUP-12][s35], [SUP-13][s35].
  - Files: `bin` (:902-906, :1798-1802, :1829-1832), `lib/router_claude_catalog.py` (:137, :147-148), tests.
  - Accept: the background and `check` paths keep the same descriptions, and a non-JSON stdout line is skipped
    (tests).
- [ ] **Fix small routing semantics and `check` warnings.**
  - Closes: [CORE-09][s31], [CORE-10][s31], [CORE-11][s31], [N4 residual][s31], [gap D][s41].
  - Files:
    - `bin` (:1338, :1342, :1361, :1365, :1903-1913);
    - `agents/effort-*.md` (descriptions);
    - `skills/subagent-model-router/SKILL.md` (:45, :56-58);
    - `config.example.toml` (:32, :40);
    - tests.
  - Accept:
    - `model: null` is handled the same way on both clients;
    - `check` warns about `maxEffortLevel` and effort caps;
    - `check --live` probes only the active agent;
    - the docs state that Explore and explorer are never routed.
- [ ] **Sample shadow routing.**
  - Closes: [CORE-19][s32].
  - Files: `bin`, `config.example.toml` (:5), tests.
  - Accept: in shadow mode with sample rate r and a fixed seed, the number of requests the fake Jev sees is within
    three binomial standard deviations of r × launches, and no `systemMessage` is shown (test).
- [ ] **Fix and cut the Grafana dashboard.**
  - Closes: [TEL-08][s34], [TEL-13][s34], [TEL-09][s38].
  - Files: `grafana/subagent-model-router.json` (panel 11 at :704, panel 51),
    `skills/subagent-model-router/references/monitoring.md` (:117).
  - Accept:
    - panel 11 uses `reason=~"choice|policy"`;
    - panel 51 is renamed;
    - a `dropped_events`/`payload_size` delivery panel exists;
    - the panel count drops from 68 to about 15.
- [ ] **Unify local stats and rotate the journal.**
  - Closes: [TEL-12][s34], [TEL-15][s34].
  - Files: `bin` (:1446-1460, :1645-1743, :2232-2244), `lib/router_dashboard.py` (:279-280), tests.
  - Accept: tests show one reader with one default period, and journal rotation at a size cap.
- [ ] **Archive the legacy tier eval.**
  - Closes: [TEL-17][s33].
  - Files: `eval/run.py`, `eval/cases.json`, `eval/README.md`, `README.md` (:304-307).
  - Accept: the files are removed or archived, and the README Evaluation section points to the factor eval and the
    strategy eval.
- [ ] **Make the optional dashboard extras opt-in or remove them.**
  - Closes: [§3.8][s38].
  - Files: `lib/router_browser.py`, `lib/router_dashboard.py`, the OpenRouter balance code, their tests.
  - Accept: the core hook tests pass with the extras absent, and about 1,400 lines leave the default code path.
- [ ] **Remove the losing decision mechanism.**
  - Closes: [CORE-03][s32], [§3.8][s38], [§6.3][s63].
  - Files: either `lib/router_factors.py` (278 lines) plus about 60 lines of `bin` and 273 test lines, or the
    Choice path in `bin`.
  - Accept: once the strategy eval has picked a winner, only one mechanism remains and the suite passes.
- [ ] **Split `bin` incrementally.**
  - Closes: [gap B][s41].
  - Files: `bin`, new `lib/` modules for the Jev client and option building.
  - Accept: the Jev client and option building live in `lib/`, and test results are unchanged.
- [ ] **Filter models by `max_input_tokens` and measure harness noise.**
  - Closes: [backlog items 7c and 3][s41].
  - Files: `bin` (option building), `lib/router_claude_catalog.py`, `eval/`.
  - Accept:
    - a model whose `max_input_tokens` is below the estimated request size is not offered (test);
    - the share of harness noise is measured on a consented journal sample before any stripping is built.

[s31]: docs/router-audit-2026-10.md#31-prompt-and-routing-correctness
[s32]: docs/router-audit-2026-10.md#32-hook-path-cost-and-latency
[s33]: docs/router-audit-2026-10.md#33-evaluation-and-measurement-gaps
[s34]: docs/router-audit-2026-10.md#34-telemetry-and-dashboards
[s35]: docs/router-audit-2026-10.md#35-prices-and-catalogs
[s36]: docs/router-audit-2026-10.md#36-privacy-config-and-file-safety
[s37]: docs/router-audit-2026-10.md#37-documentation-drift
[s38]: docs/router-audit-2026-10.md#38-superfluous-parts
[s41]: docs/router-audit-2026-10.md#41-verdicts-on-the-backlog-and-ideas
[s52]: docs/router-audit-2026-10.md#52-static-defaults-plus-escalation-versus-per-call-jev-routing
[s53]: docs/router-audit-2026-10.md#53-per-client-defaults
[s55]: docs/router-audit-2026-10.md#55-the-core-01-prompt-replacement-and-its-quality-confound
[s61]: docs/router-audit-2026-10.md#61-telemetry-fixes-needed-first
[s62]: docs/router-audit-2026-10.md#62-metric-and-arms
[s63]: docs/router-audit-2026-10.md#63-promotion-rule
[s64]: docs/router-audit-2026-10.md#64-sample-sizes
