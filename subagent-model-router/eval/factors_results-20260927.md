# Factor policy — first live run, 2026-09-27

Dataset `eval/factors_cases.json` (46 synthetic cases, 23 EN / 23 RU), SHA-256
`dde7c52d101985de1e14f1201179c23bc69d6bd4a51777affb4bf00177183ec2`, labelled before any live request.
Provider OpenRouter, model `typesafe/jev-1.13-20260917`, 2 repeats = 92 requests, 0 failures,
mean latency 613 ms, reported cost $0.00394 in total. Raw answers: `factors_results-20260927.jsonl`.

| Metric | Policy as first written | After the post-hoc fix |
|---|---:|---:|
| Level within the acceptable band | 95.7% | 100% |
| Under-routing (level below the cheapest adequate) | 4.3% (P02/P04) | 0% |
| Over-routing (above the band) | 0% | 0% |
| Level one step above the cheapest adequate | 8 of 92 → 1→2 | 12 of 92 (1→2: 8, 3→4: 4) |
| Repeat disagreement (level / effort) | 0 / 0 | 0 / 0 |

Factor argmax accuracy against labels: reasoning 0.76, spec 0.72, verification 0.67 (mean confidence 0.58),
scope 0.82, impact 0.70, review 1.00, review depth 1.00, prior failure 0.96.

**Post-hoc fix.** Both under-routed runs were "find the cause of a flaky test; an earlier attempt failed".
Jev rated them fully specified with automated checks, so the verified discount cancelled the prior-failure
raise. The discount now applies only when reasoning is at most "ordinary implementation": passing checks
prove an implementation, not a diagnosis. The change was made after seeing these results on the same set,
so the 100% column is not an unbiased test; a new held-out set is needed to confirm it.

Verification and spec are the weakest factors (verification confidence is often below 0.6, which triggers
upward confidence raises). Over-routing by one step costs money but not correctness; it is the price of the
asymmetric rules. Synthetic tasks, small set, English-first model: no claim about real task success.
