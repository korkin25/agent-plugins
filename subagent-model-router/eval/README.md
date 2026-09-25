# Frozen routing benchmark

`cases.json` is a pre-registered synthetic labelled set for comparing router
versions. It contains 28 cases, including English/Russian goal pairs, paired
read-only/execution variants, packet and non-packet inputs, independent review,
unknown debugging, architecture judgment, and context-boundary cases. Freeze
the file and record its SHA-256 before any live query; do not relabel cases
after observing answers.

Each case has the following schema:

```json
{
  "id": "stable-case-id",
  "group": "comparison-family",
  "language": "en|ru",
  "description": "context passed separately",
  "task": "complete synthetic task text",
  "expected": {"tier": "light|standard|heavy", "risky": false, "review": false},
  "rationale": "independent label justification"
}
```

## Labelling rubric

Label the **complete authorized task**, including constraints such as "do not
send" or "deployment is authorized". Do not infer an action from a heading,
filename, isolated keyword, or incidental context.

`tier` is raw task complexity, judged independently of `risky` and `review`:

- `light`: a bounded lookup, listing, quotation, or fully specified mechanical
  edit with an obvious result.
- `standard`: ordinary engineering work across several sources, a comparison or
  synthesis, or code/test work under a clear specification.
- `heavy`: independent review/audit, unknown-cause debugging, security work,
  consequential architecture choice, or other work requiring deep judgment.

`risky` is true only when the authorized task can delete/corrupt data, publish
or send outside the machine, change a shared system, or expose secrets. The
task can be raw `light` or `standard` and still be risky. `review` is true only
when the task independently checks finished work against requirements and
recommends or decides approval/rejection. A request merely to read a file named
"review" is not review.

The expected routed tier is derived, rather than stored separately: raw `heavy`
routes `heavy`; any `risky` or `review` case also routes `heavy`; otherwise the
routed tier equals raw `tier`. This matches the current routing policy while
keeping complexity labels useful if policy changes.

## Evaluation protocol

Use the same fixed model, question set, thresholds, description/task fields,
and request implementation for old and new versions. Run each logical request
twice per version, interleaved in a randomized order, and retain only
non-sensitive evidence: case id, version, run ordinal, timestamps, outcome,
returned probabilities/tier/rule, latency, state payload size, and a state
digest. Do not store API keys, authorization headers, raw credentials, or
provider request payloads outside the defined synthetic state.

The benchmark should report:

- raw-tier correctness and routed-tier correctness;
- risky false positives and false negatives;
- review false positives and false negatives;
- under-routing (expected routed `heavy`, observed non-heavy);
- paired-case change correctness, especially read-only versus authorized
  execution and English/Russian goal pairs;
- repeat variability failures (different labels for the same case/version),
  latency, and payload-size distribution.

The task text intentionally has one long non-packet fallback case where the
decisive instruction occurs after neutral context. It is a diagnostic
adequacy-boundary case, not a claim that a router must overcome an explicitly
documented extraction limit. The redaction-boundary case contains only an
already-redacted placeholder; this dataset includes no real or credential-like
values.

Synthetic labels measure alignment with this rubric, not real task success,
cost, safety in production, or token savings. Results should be reported as a
bounded old-versus-new comparison with failures and uncertainty, not as proof
of general routing quality.
