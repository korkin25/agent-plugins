# Frozen task set

The offline set for the paired strategy eval ([audit §6.2](../../docs/router-audit-2026-10.md#62-metric-and-arms),
[§6.4](../../docs/router-audit-2026-10.md#64-sample-sizes)). Every task is a delegation packet — the text a lead agent
would hand a subagent — with a starting workspace and an automated pass/fail check. Every arm of the eval runs every
task, so arms differ only in the model, the effort and the prompt they launch with.

The set spans domains on purpose: routing pays off only if cheap launches solve some tasks and fail others, so the
tasks must differ in kind and in difficulty.

| Domain | What the subagent does |
|---|---|
| `math` | computes an exact answer: arithmetic, number theory, combinatorics, probability, algebra, geometry |
| `logic` | solves a constraint or deduction puzzle, a schedule or an assignment |
| `code` | implements a function, a class or a small program to a specification |
| `tooling` | writes an SQL query, a regular expression, a shell pipeline or a config to a specification |
| `debug` | finds and fixes the bug behind a reported failure |
| `review` | reviews code or a change against its specification and lists the defects |
| `text` | extracts, classifies, restructures or rewrites text under stated constraints, in English and in Russian |
| `data` | answers questions about CSV, JSON or log files |

Difficulty: `1` — one step, no trap; a small model at low effort should pass. `2` — several steps or one trap.
`3` — a long chain, an edge case most first attempts miss, or a long input; a frontier model at medium effort may
still fail sometimes.

The tasks so far are synthetic. None is drawn from a user's session, so no consent is involved; a packet drawn from
real sessions may join only with the user's recorded consent and a new `source` value. A task taken from a public
dataset likewise needs its own `source` value and fields that pin where it came from.

## Stages

The set grows in stages, each a task of the [P0 queue](../../queues/p0.toml). Stage 1 is the portion the bench is
debugged on: reviewed tasks in four domains. Stage 2 grows the set to 190: it adds the other four domains and
difficulty 3 in every domain. `tests/test_taskset.py` holds a set at or past a stage's size to that stage's spread:

| Stage | Tasks | Domains | Per domain | Each domain covers difficulties | In Russian |
|---|---|---|---|---|---|
| 1 | 50 | `math`, `code`, `debug`, `text` | at least 8 | any; the set as a whole covers 1, 2 and 3 | at least 10 |
| 2 | 190 | all eight | at least 20 | 1, 2 and 3 | at least 19 |

Stage 1 holds a few tasks more than its size, so the bench may retire a defective one without breaking the stage.
Merged tasks never change ([Freezing](#freezing)), so a stage only adds tasks.

## Layout

```
taskset.py              list | prepare | check | validate | manifest
MANIFEST.json           the frozen set: a SHA-256 per task and one for the whole set
tasks/<domain>-NN/
  task.json             metadata, below
  packet.md             the packet; {workdir} stands for the absolute path of the task's working directory
  check.py              python3 -I -B check.py WORKDIR — exit 0 pass, 1 fail; the last stdout line is the reason
  workspace/            the files the subagent starts with (optional)
  solution/             a reference result, laid over the workspace: the check must pass
  broken/<variant>/     plausible wrong results, each laid over the workspace: the check must fail
  ...                   anything else is the check's own data (hidden tests, expected values)
```

`task.json`:

```json
{
  "id": "math-01",
  "domain": "math",
  "difficulty": 1,
  "title": "Count multiples of 3 or 5 that are not multiples of 15",
  "language": "en",
  "outputs": ["answer.txt"],
  "source": "synthetic",
  "check_timeout_seconds": 10,
  "tags": ["counting", "inclusion-exclusion"]
}
```

`language` is the packet's language. `outputs` are the paths, relative to the workdir, that the check reads; the
packet names each of them. An optional `notes` string may explain the trap to a reviewer.

## Commands

```
python3 taskset.py list                      # tasks and the domain x difficulty table
python3 taskset.py prepare math-01 DEST      # copy the workspace into DEST, print the packet for DEST
python3 taskset.py check math-01 DEST        # {"status": "pass" | "fail" | "timeout" | "error", ...}
python3 taskset.py validate [-v] [ID ...]    # see below; tests/test_taskset.py runs it in CI
python3 taskset.py manifest [--write]
```

`check` exits 0 on pass, 1 on fail or timeout, 2 when the check itself broke. `validate` requires, for every task:
the files and metadata follow this README; the check **fails** on the untouched workspace, **passes** on the
solution twice in a row, and **fails** on every broken variant — each a clean exit 1, never a timeout or a crash.

## Running the set

The runner (a later step; [task-panes](../../../task-panes) can drive it) prepares each task in a fresh empty
directory outside any repository and gives the subagent only the packet. The subagent must not see this directory:
hide `eval/taskset` of the repository checkout and of every installed copy of the plugin (for task-panes, the
sandbox's `hidden` list). The set is public, so it may reach future training data; arms are compared on the same
tasks, but absolute pass rates may read high.

A run records the manifest's set hash; results from different hashes are not compared.

## Freezing

Once merged, a task's files never change. A defective task is retired: its id moves to `retired` in
`MANIFEST.json` with the reason and its directory is removed; a replacement takes a new id. Every change bumps
`version` and runs `taskset.py manifest --write`.

## Writing a task

- **Self-contained packet**, written like a real hand-off. Fields: `TASK`, `WORKDIR`, `READ`, `EDIT`, `CHECKS`,
  `OUTPUT`, optionally `MUST_NOT`. It names every output file and its exact format. It never reveals the expected
  answer, the hidden check or the trap. `CHECKS` may point at visible tests in the workspace.
- **One verifiable truth.** Exactly one correct answer, or a check that verifies the constraints rather than one
  answer. Expected values are computed by independent code (brute force where possible), never by hand.
- **A fair check.** It accepts every output the packet's wording allows (whitespace, a trailing newline, JSON key
  order, letter case where the packet leaves it open) and rejects what the wording rules out. Text checks test
  stated, countable constraints — required facts, word limits, forbidden phrases, structure — never taste.
- **A robust check.** Python 3.11 standard library only, no network, deterministic. Garbage, a missing file or an
  exception in the subagent's code is a fail (exit 1), never a crash. It runs the subagent's code in a subprocess
  with its own timeout, so a hang is a fail and not a timeout of the check. It writes nothing into the workdir
  (use `TMPDIR`), reads only the workdir and its own task directory, and takes under 10 s on the solution.
- **Plausible broken variants**: the mistakes a hurried solver actually makes — the trap, an off-by-one, a missed
  edge case, an ignored constraint. At least one per task, at least two for difficulty 3.
- **Small**: a packet under 12,000 characters, a task directory under 256 KiB. Fictional names and data only; no
  personal data, and no strings that look like credentials or API keys.
