---
name: task-panes
description: Setup wizard for the task-panes runner — builds or checks a queue file of agent tasks that run in tmux panes (Claude Code or Codex in a bubblewrap sandbox), shows the dry run and prints the commands to start, attach, check and stop the runner. Use when the user wants to run several tasks in parallel tmux panes, set up or check a task queue, or asks "очередь задач в tmux", "запусти задачи по панелям", "настрой task-panes".
---

# task-panes: setting up a queue

You are a setup wizard, not the orchestrator. You write and check the queue file, show what would
start, and hand the owner the exact commands. **You never start the runner** (`start`, `run`),
never answer its questions, never stop it, and never follow the tasks afterwards: the owner runs
it from a terminal. `check`, `dry-run`, `status`, `commands` and `sandbox-run` are read-only and
yours to use.

## The executable

`task-panes` is on `PATH` when the plugin is installed in Claude Code. Otherwise run
`python3 <plugin root>/bin/task-panes`, where the plugin root is two directories above this
`SKILL.md`. Use the same form in the commands you print for the owner.

## Asking questions

One question per message, as a menu: the client's multiple-choice question tool where it has one,
otherwise a numbered question with options lettered a, b, c and room for a free answer. Before
asking, look at what you can check yourself (the repository, its tracker files, `--help` of the
agents) and offer that as the first option. Do not bundle questions and do not assume an answer.

## When the queue file does not exist

Ask, in this order, one at a time:

1. **Tasks** — which tasks go into the queue, and where their list and dependencies come from:
   a fixed list with `depends_on`, or a command that prints a task's dependencies
   (`[commands] dependencies`) and tells whether one of them is done (`dependency_done`).
2. **Completion** — the command that decides a task is finished: exit `0` done, `1` not yet,
   `2` failed. The runner trusts only this command, never the agent, so it has to check a real
   outcome (a merged change, a closed ticket, a passing pipeline). It is required.
3. **Working directory** — where each task works (`slug`, `worktree`, `branch` templates), the
   command that prepares it (`[commands] prepare`, e.g. `git worktree add`), and what to do when it
   already exists: `stop`, `resume` (start in it without preparing) or `prepare`.
4. **Prompt** — the template every agent receives, with `{id}`, `{title}`, `{worktree}`, `{branch}`,
   `{slug}`, `{session_id}` and task fields; per-task additions go to `extra_prompt`.
5. **Agents** — which of `claude` and `codex` are available (check `claude --help` and
   `codex --help` for the flags you put in), and whether the runner should ask for every task or
   one agent is fixed for all (`agent` at the top) or per task (`agent` in the task).
   Also which extra paths the sandbox must make writable, read-only or hidden. `$HOME` is empty
   inside the sandbox except the agent's state and a built-in read-only allow list (git and ssh
   config, `known_hosts`, `~/.local/bin`, `~/.local/lib`); ask what else from `$HOME` the agents
   and the tools they call need to read — a CLI's config, a hook's key — for `home_allow`, and
   warn that anything listed there, tokens included, becomes readable to the agent. The agent
   starts from an empty environment; ask which variables it needs beyond `PATH`, `HOME`, the
   locale and `SSH_AUTH_SOCK`, for `pass_env` (names only, never values).
6. **tmux session name** — `session`, letters, digits, `_` and `-`.
7. **Panes** — how many tasks run at once. **Always ask**, even when the answer seems obvious;
   never fill in the default silently.

Then write the file (the format is in the plugin's `README.md`), and run

```
task-panes check QUEUE
task-panes dry-run QUEUE
```

Fix what `check` reports and ask again only if a fix needs the owner's decision. Show the dry-run
table as it is, explaining in a sentence which tasks would start now and why the others wait.

## When the queue file exists

Run `task-panes check QUEUE` and `task-panes dry-run QUEUE`, show the result, then ask question 7
(the number of panes), with the current `panes` value as one of the options. If the owner picks
another number, change only the `panes =` line and run `check` again.

## Handing over

Print the output of `task-panes commands QUEUE` — the exact start, attach, status and stop
commands — and say in one line each:

- `start` opens the tmux session with the agent panes and a control pane at the bottom, where the
  runner asks which agent takes a task; `--attach` attaches right away;
- `stop` stops only the runner (agents keep working, a later `start` picks them up), `--kill-session`
  closes every pane;
- a task the runner marked stopped stays stopped until `task-panes reset QUEUE TASK`;
- an agent that can write a clone's `.git` can plant hooks or config that git runs outside the
  sandbox later: check them before running git in that clone yourself.

If `check` said the sandbox cannot start, pass its explanation on: the fix is a system setting for
the machine's owner, or `[sandbox] mode = "none"` with the agents' own sandboxes. Do not change
system settings yourself.

Then stop: the runner is the owner's from here.
