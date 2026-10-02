# Task queues

Every task of this project is an entry of a [task-panes](../../task-panes) queue: the runner starts each task in
its own git worktree and tmux pane, in a bubblewrap sandbox, once the tasks it depends on are done. The owner
starts and stops the runner; agents never do.

| Queue | Tasks |
|---|---|
| [p0.toml](p0.toml) | the P0 items of [TODO.md](../TODO.md) |

## A task

A queue task names the TODO item it closes by its exact bold title (`todo`), and may carry `min_tasks`, the size
the [frozen task set](../eval/taskset/README.md#stages) must reach. It runs on its own branch in
`/var/tmp/agent-plugins-<session>/<slug>/wt`, made from `origin/main`; its `TMPDIR` is the `tmp/` next to it.

The runner takes a task as done only when [queue_check.py](queue_check.py) `done` says so, never on the agent's
word. On `origin/main` (the queue's `refresh` fetches it):

1. a commit message has the line `Queue-Task: <id>`, the task's merge commit; the newest such commit counts;
2. the item `todo` in TODO.md is checked, `- [x]`;
3. `MANIFEST.json` of the task set lists at least `min_tasks` tasks, when the task has that field;
4. every GitHub check run on that merge commit is green (success, neutral or skipped). Each push to main runs its
   own CI to the end, and a later commit's runs do not count, because a run checks only the files its push changed.

`done` exits 0 when all four hold, 1 while one is missing, 2 when the setup is broken (no such TODO item, origin is
not on GitHub); the last line of its output says which. An agent runs the same check from its worktree:

```
python3 -B subagent-model-router/queues/queue_check.py done
```

CI state comes from the GitHub API without a token, which allows 60 requests an hour; answers are cached in
`~/.cache/agent-plugins-queues/ci/`, a green one for good and any other for four minutes.

## Merging

The task's agent merges its own branch:

```
git fetch origin && git rebase origin/main        # and run the tests again
git switch --detach origin/main
git merge --no-ff <branch> -m "Merge <branch>: <summary>" -m "Queue-Task: <id>"
git push origin HEAD:main
```

A rejected push means main moved: rebase again and repeat. A red CI is fixed on the branch and merged again with the
same `Queue-Task` line. A task may merge in several batches, each with the line; it is done once the last batch checks
the TODO item.

## Cleanup

`refresh` also runs `queue_check.py prune QUEUE`. For every task that is done, it removes the worktree, the branch
and `/var/tmp/agent-plugins-<session>/<slug>/`, and the session directory once it is empty, but only when the worktree
has no uncommitted changes and the branch has no commits outside `origin/main`. Otherwise it leaves them and says why.

## Running a queue

From the repository root:

```
task-panes check subagent-model-router/queues/p0.toml      # the file and the machine
task-panes dry-run subagent-model-router/queues/p0.toml    # what would start now, and why the rest waits
task-panes commands subagent-model-router/queues/p0.toml   # start, attach, status and stop
```

The runner asks in its control pane which agent, Claude Code or Codex, takes each task. `panes` sets how many
tasks run at once. The sandbox makes the repository's `.git` writable, so an agent can commit, fetch and push from
its worktree. That also lets it plant hooks or config that git runs outside the sandbox later: check `.git/hooks`
and `.git/config` before running git in this clone yourself.

## Adding a task

1. Add the item to TODO.md. Its bold title is its key and stays unchanged from then on.
2. Add a `[[tasks]]` entry with a new `id`, a `name` (it becomes the branch `p0/<name>`), the `todo` title and
   `depends_on`.
3. Run `task-panes check` and the tests: `tests/test_queue_check.py` checks that every `todo` names an item of
   TODO.md and every dependency exists.
