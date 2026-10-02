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

1. a commit on the first-parent line of main has the message line `Queue-Task: <id>`, the task's merge commit; the
   newest such commit counts;
2. the item `todo` in TODO.md is checked, `- [x]`;
3. `MANIFEST.json` of the task set lists at least `min_tasks` tasks, when the task has that field;
4. every GitHub Actions workflow run on main for that merge commit has finished green (success, neutral or skipped).
   A later commit's runs do not count. Each push to main runs its own CI to the end, and for a merge with a
   `Queue-Task` line `validate.yml` checks everything changed since that task's first merge, not just the last push.

`done` exits 0 when all four hold, 1 while one is missing, 2 when the setup is broken (no such TODO item, origin is
not on GitHub); the last line of its output says which. An agent runs the same check from its worktree:

```
python3 -B subagent-model-router/queues/queue_check.py done
```

CI state comes from the GitHub API without a token, which allows 60 requests an hour per address; answers are cached
in `~/.cache/agent-plugins-queues/ci/`, a green one for good and any other for four minutes. The check trusts the
clone's `origin` remote and the `origin/main` that `refresh` fetches into it.

## Merging

The task's agent merges its own branch:

```
git fetch origin && git rebase origin/main        # and run the tests again
git switch --detach origin/main
git merge --no-ff <branch> -m "Merge <branch>: <summary>" -m "Queue-Task: <id>"
git push origin HEAD:main
```

Push each merge on its own, so that CI runs on that commit. A rejected push means main moved: rebase again and
repeat; never force-push. A red CI is fixed on the branch and merged again with the same `Queue-Task` line. A
cancelled run is re-run by the owner instead: a new merge would not redo it, since a release runs only for the push
that bumps a version. A task may merge in several batches, each with the line; it is done once the last batch checks
the TODO item.

## Cleanup

`refresh` also runs `queue_check.py prune QUEUE`. It touches only tasks the runner has recorded as done, their panes
closed, that still pass `done`. For each it removes the worktree, the branch and
`/var/tmp/agent-plugins-<session>/<slug>/`, and the session directory once it is empty, but only when the worktree
lies in such a directory, has no uncommitted changes, and neither its HEAD nor the branch has commits outside
`origin/main`. Otherwise it leaves them and says why.

`task-panes dry-run` and `status` run `refresh` too, so they fetch and prune; add `--no-refresh` to only look.

## Running a queue

From the repository root:

```
task-panes check subagent-model-router/queues/p0.toml                 # the file and the machine
task-panes dry-run --no-refresh subagent-model-router/queues/p0.toml  # what would start now, why the rest waits
task-panes commands subagent-model-router/queues/p0.toml              # start, attach, status and stop
```

The runner asks in its control pane which agent, Claude Code or Codex, takes each task. `panes` sets how many
tasks run at once. The sandbox makes the repository's `.git` writable, so an agent can commit, fetch and push from
its worktree. That also lets it plant hooks or config, or repoint `origin`, and the queue's own `refresh`, `prepare`
and `done` run git on that `.git` outside the sandbox, as does the owner in this clone: check `.git/hooks` and
`.git/config` before trusting either. `queue_check.py` ignores `refs/replace`, which could otherwise make a commit
show another commit's message and files.

## Adding a task

1. Add the item to TODO.md. Its bold title is its key and stays unchanged from then on.
2. Add a `[[tasks]]` entry with a new `id`, a `name` (it becomes the branch `p0/<name>`), the `todo` title and
   `depends_on`.
3. Run `task-panes check` and the tests: `tests/test_queue_check.py` checks that every `todo` names an item of
   TODO.md and every dependency exists.
