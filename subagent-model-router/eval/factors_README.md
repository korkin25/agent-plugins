# Factor-policy benchmark (factors_v1)

## Purpose

This benchmark measures how well Jev's answers to the factor questions in
`lib/router_factors.py`, combined by `assess()`, produce a capability level and an
effort class that are adequate for a subagent task. The most important question is
whether the policy **under-routes**: whether it gives a task a weaker level than
the rubric requires. It does not evaluate the direct Choice question, model prices,
task success or cost savings. The frozen pre-0.5.0 benchmark (`README.md`,
`cases.json`, `run.py`) is a separate benchmark and stays unchanged.

## Pre-registration

The labels in `factors_cases.json` were written from the rubric and the task text
before any live query was made. Do not relabel cases after you see answers. If a
label turns out to be wrong, add a new versioned file and record why.

```
factors_cases.json  SHA-256  dde7c52d101985de1e14f1201179c23bc69d6bd4a51777affb4bf00177183ec2
```

Each live run records `dataset_sha256` in its meta line. Compare it with this hash.

## Dataset

The file has 46 synthetic cases: 23 English and 23 Russian, with a mix of packet
style (`TASK:/ROLE:/...`) and plain prose. Seven groups are pairs of variants that
differ in one decisive property. Each variant appears in English and in Russian, so
each of these groups has four cases:

| group | decisive property | variants |
|---|---|---|
| readonly_vs_execution | impact | read a deploy config / apply it to shared staging |
| specified_vs_unspecified | spec | exact `--dry-run` feature with a test / only the goal |
| tested_vs_untested | verification | stated unit tests / only a person reading |
| review_vs_named_file | review | independent acceptance review / edit of `*-review.md` |
| prior_failure_vs_first | prior_failure | flaky-test diagnosis / the same after a failed fix |
| local_vs_cross_component | scope (with reasoning 3) | concurrency fix in one module / across four packages |
| harmless_vs_data_loss | impact | list old backups / delete the only copies |

The remaining groups test specific points. `review_depth` compares a checklist
review (depth 0) with a behaviour review (depth 1), with four cases.
`external_message` compares a local draft with a post that reaches external
subscribers, also with four cases. `frontier_security`, `design_tradeoff`,
`translation`, `rename_scope` (a wide mechanical change) and `plain_long` (the
decisive instruction comes after neutral context) have one English and one Russian
case each.

The schema of a case:

```json
{
  "id": "R01-deploy-read-en", "group": "readonly_vs_execution", "pair": "deploy",
  "language": "en|ru", "style": "packet|plain",
  "description": "...", "task": "...",
  "expected": {
    "min_level": 1, "max_level": 2, "effort_min": "low", "effort_max": "medium",
    "factors": {"reasoning": 0, "spec": 2, "verification": 0, "scope": 0, "impact": 0,
                "review": false, "review_depth": null, "prior_failure": false}
  },
  "rationale": "..."
}
```

`review_depth` is labelled only when `review` is true; otherwise it is `null`,
because `assess()` ignores it for tasks that are not reviews.

## Rubric

Each factor gets the index of the level description in `QUESTIONS` that fits the
**complete authorized task** best. Headings, filenames, incidental context and
forbidden actions are not the task.

- **reasoning**: 0 lookup, listing, quoting, reformatting, translation or a
  mechanical edit; 1 ordinary implementation or comparison under a stated
  specification; 2 diagnosing an unknown cause, or choosing a design among
  tradeoffs; 3 security, concurrency, data integrity, or contracts between systems.
- **spec**: 0 only the goal is stated; 1 the goal and the approach are stated;
  2 exact steps, target files and expected result are stated.
- **verification**: 0 only a person reading the work can catch an error; 1 partly
  stated checks and partly judgment; 2 stated automated checks or an exact expected
  output.
- **scope**: 0 one file or one small item; 1 several files in one component;
  2 several components or the whole repository.
- **impact**: 0 harmless and easy to redo; 1 wasted time, but the damage stays
  local; 2 data loss, broken shared systems, leaked secrets, or messages that reach
  people outside.
- **review**: true only when the task asks for an acceptance decision on someone
  else's finished work. **review_depth**: 0 checklist or format; 1 behaviour against
  stated requirements and tests; 2 independent judgment of correctness, regressions,
  security or design.
- **prior_failure**: true only when the task says that an earlier attempt at the
  same work failed. A failing test on its own is not a prior failure.

The labelling conventions used for this file:

- **impact.** Read-only work and trivially reverted edits in the worktree are 0.
  Code changes whose error costs real time are 1. Execution against shared
  systems, destructive operations and sends to outsiders are 2 only when the task
  authorizes them.
- **verification 2.** The task must itself state the check or the exact output.
  An output format alone, such as "two lines", does not count.

The required level comes from the labels through the combination rules of
`assess()`, applied to one-hot, fully confident answers:

- The base level is `(1,2,3,3)[reasoning]`.
- The impact floor is `(1,2,3)[impact]`.
- `reasoning 3` with `scope 2` gives level 4.
- A review has the floor `(2,3,4)[review_depth]`.
- The level drops by one when spec is 2 and verification is 2, impact is below 2,
  the task is not a review and the level is above 1.
- The level rises by one on prior failure.

The effort class is `EFFORT_BY_REASONING[reasoning]`. It rises by one step when
spec is 0, and a review with depth 2 gets at least `high`.

- `min_level` is the rubric level: the cheapest level that is adequate.
  `max_level` is `min(min_level + 1, 4)`, the tolerated band.
- `effort_min` is the rubric effort, and `effort_max` is one step higher, up to
  `xhigh`.

`--check-labels` recomputes the rubric level for every case, and a unit test
enforces it. The bands are a function of the labels, so a labelling error shows up
as a factor error, not as an unexplained band.

## Protocol

1. Check the file with `python3 eval/factors_run.py --check-labels`. It must end
   with `problems=0` and print the SHA-256 above.
2. Run it live once, explicitly:
   `python3 eval/factors_run.py --live --output eval/results-factors-YYYYMMDD.jsonl --repeats 2`.
   - Every case is sent once per repeat, in a fixed shuffled order (seed
     20260927).
   - The run uses the plugin's own path: `load_config` → `read_key` →
     `build_state` → `ask_jev` / `_exchange`.
   - Each request carries only `router_factors.questions()` and no selection
     question. The Choice parser needs a selection, so the runner replaces it with
     a factor-only parser for this process.
   - The default time budget per request is 20 s (`--timeout`). The hook's 3 s
     budget is meant for a different request size.
   - The output file is created exclusively: an existing file is never
     overwritten.
   - Each row stores only the case id, repeat, the returned probabilities,
     confidences and noul values, latency and usage (plus the error kind when a
     request fails).
   - The run never stores keys, headers, request bodies or response ids.
3. Compute the metrics offline, as often as needed:
   `python3 eval/factors_run.py --answers eval/results-factors-YYYYMMDD.jsonl [--report out.json]`.
   It computes levels with the current `assess()` and the policy defaults
   (`min_confidence` 0.6, `strict_confidence` 0.8, noul thresholds 0.5).

## Metrics

| metric | meaning |
|---|---|
| `factors.<score>.accuracy` / `mean_confidence` | argmax against the label; `review_depth` is scored only on review cases |
| `factors.<noul>` | accuracy at the policy threshold, false positives and negatives, and the mean probability for true and false labels |
| `level.under_routing_rate` | **primary**: the share of answers with level below `min_level` (also `mean_under_shortfall`) |
| `level.within_band_rate` | the share with `min_level ≤ level ≤ max_level` |
| `level.over_routing_rate` / `mean_overshoot_above_max` | level above `max_level`, and by how much |
| `level.mean_excess_above_min` | the mean distance above the cheapest adequate level, over answers that are above it |
| `level.confusion_min_level_to_observed` | counts of `min_level->observed` |
| `effort.within_band_rate` | the effort class is inside `[effort_min, effort_max]` |
| `repeats.*` | cases whose level, effort or factor argmaxes differ between repeats |
| `groups` | under, within and over counts per group |
| `worst_cases` | sorted by shortfall first, then overshoot, then the number of mismatched factors |
| `failures` | transport errors and answers that `router_factors.parse` rejects |

When you report paired results, also look at both variants of each `pair`: a
policy that routes both variants the same way has missed the decisive property,
even when each variant alone is within its band.

## Running the tests

```
python3 -m unittest eval.test_factors_run
python3 eval/factors_run.py --help
python3 eval/factors_run.py --check-labels
```

The tests use only synthetic answers. They do not touch the network, the config or
the keys.

## Limitations

- **Synthetic and small.** There are 46 cases in 14 groups, so one case in a group
  moves the rates by a lot. Report counts together with the rates. The results
  measure agreement with this rubric, not real task success, safety or savings.
- **One labeller, circular bands.** One author wrote the labels. The bands are
  derived from the labels through `assess()`, so the benchmark tests the factor
  answers and the combination rules together. It cannot show that the combination
  rules themselves are right. Examples are the verified discount to level 1 for
  specified and tested feature work, and review depth 2 always meaning level 4.
- **English-first model.** Jev's primary language is English. The Russian cases
  measure the gap, and they are translations, not native tasks.
- **Ambiguous boundaries.** Some rubric boundaries are open to interpretation:
  impact 0 versus 1 for worktree edits, verification 2 for "exact expected output",
  reasoning 1 versus 2 for small unspecified features, and review of a checklist.
  They follow the conventions above. Treat disagreements on those factors as
  possible label noise, not as clear errors.
- **Policy defaults only.** Metrics use the default thresholds. A user config with
  other thresholds needs a separate offline computation.
