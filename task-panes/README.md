# task-panes

Runs a queue of agent tasks in one tmux window: every pane is an interactive Claude Code or Codex
session working on one task, so you answer its questions right there. A task starts when its
dependencies are done, and it is closed only when **your project's own completion check** says so —
never on the agent's word.

- One tmux session, one window, N panes stacked on top of each other, plus a small control pane at
  the bottom where the runner asks which agent should take the next task.
- Before a task starts, a command from the queue prepares its working directory (for example
  `git worktree add` from a fresh `origin/main`).
- Every poll (tens of seconds) the runner runs the completion check: exit `0` — done, the pane
  closes and the next ready task opens; `1` — not yet; `2` — failed.
- A failed check, or an agent that exited while the check does not say done, marks the task stopped;
  it is **never restarted automatically**. Once its agent has exited, the pane moves to a tmux window
  of its own named `<id> stopped` — still open, with the explanation — and the next ready task
  takes its place. A task stopped while its agent still runs keeps its slot until the agent exits.
- The runner keeps its state in a file and survives its own restart: a task whose pane is still
  alive is never launched a second time.
- Every agent runs inside a [bubblewrap](https://github.com/containers/bubblewrap) sandbox from an
  empty environment: full network, the filesystem read-only except the task's own paths and the
  agent's state, `$HOME` empty except an allow list, and the sockets that run commands outside the
  sandbox (session bus, `systemd --user`, docker, the tmux server) hidden. It limits accidents, not a determined attacker: see
  [what it does not stop](#what-the-sandbox-does-not-stop).

Python 3.11+ (standard library only), tmux and git; bwrap for the sandbox.

## Commands

```
task-panes check    QUEUE            # validate the file, probe tmux and the sandbox
task-panes dry-run  QUEUE            # done / ready / waiting / stopped, launches nothing
task-panes status   QUEUE            # the same table, while the runner works too
task-panes start    QUEUE [--attach] # start the runner in the session's control pane
task-panes run      QUEUE            # run the runner in the current terminal instead
task-panes stop     QUEUE [--kill-session]
task-panes answer   QUEUE TASK AGENT # choose the agent for a task from another terminal
task-panes reset    QUEUE TASK       # make a stopped task startable again
task-panes commands QUEUE            # print the exact start / attach / status / stop commands
task-panes sandbox-run QUEUE --task T --agent A -- CMD...   # try a command in a task's sandbox
```

`--socket NAME` before the command uses `tmux -L NAME` instead of the default server.

In the control pane: a number or an agent name answers the current question, `TASK AGENT` answers
for another task, `s` shows the table, `reset TASK`, `h` for help, `q` stops the runner. `stop`
without `--kill-session` stops only the runner; agents keep working, and a later `start` picks
them up again instead of launching them twice.

## Queue file

```toml
session = "work"                 # tmux session name
panes = 2                        # agent panes at once
poll_seconds = 30
worktree_exists = "stop"         # prepare | stop | resume — see below
slug = "{id_lower}"
worktree = "~/src/project-worktrees/{slug}"
branch = "feature/{slug}"
prompt = "Work on {id} ({title}) in {worktree}, branch {branch}. Session {session_id}."
pass_env = ["PROJECT_HOST"]      # extra variable names the agent gets (names only)

[env]                            # added to the environment of the commands below
REPO = "~/src/project"

[commands]                       # run with sh -c in the queue's directory
refresh = 'git -C "$REPO" fetch --quiet origin'
done = 'my-tracker is-done "$TP_ID"'          # 0 done, 1 not yet, 2 failed; required
dependencies = 'my-tracker deps "$TP_ID"'     # 0 + one id per line; 1 = not ready yet
dependency_done = 'my-tracker is-closed "$TP_DEP"'   # 0 done, 1 not done
prepare = 'git -C "$REPO" worktree add -b "$TP_BRANCH" "$TP_WORKTREE" origin/main'

[agents.claude]
command = ["claude", "--dangerously-skip-permissions", "--session-id", "{session_id}", "{prompt}"]

[agents.codex]
command = ["codex", "--dangerously-bypass-approvals-and-sandbox", "-C", "{worktree}", "{prompt}"]
prompt_prefix = "Start subagents with spawn_agent and fork_turns=\"none\"."

[sandbox]
writable = ["{worktree}", "~/src/project/.git", "~/.cache/project-{slug}"]
readonly = ["~/.local/state/project"]
home_allow = ["~/.config/glab-cli"]   # more of $HOME, read-only
hidden = ["/srv/private"]
tmpdir = "/var/tmp/project-{session_id}/{slug}"

[[tasks]]
id = "T-1"
title = "First task"

[[tasks]]
id = "T-2"
title = "Second task"
agent = "codex"                  # no question for this one
depends_on = ["T-1"]             # in addition to what `dependencies` prints
extra_prompt = "Also check the benchmarks."
```

Placeholders in `slug`, `worktree`, `branch`, `prompt`, `extra_prompt`, agent commands and sandbox
paths: `{id}`, `{id_lower}`, `{title}`, `{slug}`, `{worktree}`, `{branch}`, `{session_id}`,
`{agent}`, `{session}`, `{queue_dir}`, `{prompt}` (agent commands only), keys of `[vars]` and of the
agent's `vars`, and any extra field of the task. `{{` and `}}` are literal braces; an unknown name
fails at `check`, not at launch.

Commands see `TP_ID`, `TP_TITLE`, `TP_SLUG`, `TP_WORKTREE`, `TP_BRANCH`, `TP_SESSION`,
`TP_SESSION_ID`, `TP_QUEUE`, `TP_QUEUE_DIR`, `TP_DEP` (in `dependency_done`) and `TP_FIELD_<NAME>`
for extra task fields. The last line of a command's output becomes the reason shown in the table.

`{session_id}` is a UUID the runner generates for each launch; Claude Code receives it through
`--session-id`, so the session can be found and resumed later.

**Choosing the agent.** A task's `agent`, or the queue's top-level `agent`, fixes it. Otherwise,
when more than one agent is configured, the runner asks in the control pane before the task starts;
until you answer, that task waits and the other panes keep working.

**An existing working directory.** `worktree_exists` (top level or per task) decides what happens
when the worktree is already there: `prepare` runs the prepare command anyway, `stop` marks the task
stopped with the reason, `resume` skips preparation and starts the agent in the existing directory —
for a task whose work is already in progress.

## Sandbox

With `mode = "bwrap"` (the default) the agent runs as

```
bwrap --die-with-parent --unshare-pid --unshare-ipc --ro-bind / / --dev-bind /dev /dev \
      --tmpfs /dev/shm --proc /proc --tmpfs /tmp --tmpfs /run/user/$UID --tmpfs $HOME ... \
      --unsetenv DBUS_SESSION_BUS_ADDRESS --unsetenv TMUX --unsetenv TMUX_PANE ...
```

(`task-panes sandbox-run QUEUE --task T --print -- true` prints the exact command.)

- the whole filesystem is **read-only**; writable are the task's worktree, the queue's `writable`
  paths, `tmpdir` (exported as `TMPDIR`) and the agent's own state: `~/.claude`, `~/.claude.json`
  and its caches for `claude`, `~/.codex` and its caches for `codex` (override per agent with
  `writable`);
- **`$HOME` is an empty tmpfs.** Only the paths above and a read-only allow list come back, each
  where it exists. The built-in list is what git, ssh, glab, python3 and the agents' installs read,
  found by tracing them: `~/.gitconfig`, `~/.config/git`, `~/.ssh/config`, `~/.ssh/known_hosts`
  (never the keys: ssh signs through `SSH_AUTH_SOCK`), `~/.local/bin`, `~/.local/lib` (Python user
  packages) and the usual Node install roots (`~/.nvm`, `~/.volta`, `~/.npm-global`, `~/.bun/bin`,
  `~/.local/share/pnpm`). Everything else — ssh keys, `~/.kube`, `~/.aws`, `~/.docker`,
  `~/.config/gh`, `~/.netrc`, `~/.git-credentials`, other tools' tokens, documents — is simply
  not there. The queue's `home_allow` adds paths (a CLI's config the agent must use, for example
  `~/.config/glab-cli`, which holds its token); files the agent creates in `$HOME` outside its
  state vanish when it exits. `~/.claude.json` comes back as a single bound file, so Claude Code's
  atomic save (a temp file renamed over it) fails with `EBUSY` and it rewrites the file in place
  instead: the settings are kept, but that write is not atomic;
- own process and IPC namespaces: the agent sees only its own processes, and `/dev/shm` is private;
- `/tmp` and the runtime directory (`$XDG_RUNTIME_DIR`, `/run/user/$UID`) are empty tmpfs. The
  runtime directory holds the session D-Bus, `systemd --user`, gpg-agent, the keyring and the
  desktop's sockets, and each of them can start a process outside the sandbox
  (`systemd-run --user …`), so none of them is passed through. The one socket that comes back is
  `SSH_AUTH_SOCK`, bound as a single file (also from `/tmp` or `$HOME`), so `git push` over ssh
  keeps working. A socket inside a hidden directory (gpg-agent's `~/.gnupg/S.gpg-agent.ssh`) stays
  hidden, so ssh there has no agent;
- the tmux server's socket directory is covered and `TMUX` / `TMUX_PANE` are removed: the agent
  cannot drive its own or other panes (`tmux send-keys`);
- container daemons' sockets (docker, podman, lxd, incus, libvirt) are replaced by `/dev/null`:
  membership in their group is root on the machine. An agent that must use docker needs
  `hide_defaults = false` with your own `hidden` list — that gives it the whole machine;
- `TIOCSTI` (typing into the pane's terminal from inside) is refused by Linux 6.2+ when
  `dev.tty.legacy_tiocsti = 0`; on a kernel that still allows it bwrap gets `--new-session`; the
  agent then loses the pane as its controlling terminal, so Ctrl-C and resize signals from tmux
  no longer reach it;
- **hidden** (an empty tmpfs or `/dev/null` on top): browser profiles, mail, keyrings, `~/.gnupg`,
  `~/.password-store`, KeePassXC settings and `~/*.kdbx` wherever a bind brings them back (a worktree
  or allowed directory inside `$HOME`), the container sockets above, plus the queue's `hidden` list
  for anything else — inside an allowed directory or outside `$HOME` (`hide_defaults = false` drops
  both built-in lists);
- the network is not restricted;
- `extra_args` are passed to bwrap as they are.

**The agent starts from an empty environment.** It gets only `PATH`, `HOME`, `USER`, `LOGNAME`,
`SSH_AUTH_SOCK` and the locale (`LANG`, `LC_ALL`, `LC_CTYPE`) from where the runner runs, `TERM` and
`COLORTERM` from its pane, the `TP_*` variables, and the names the queue lists in `pass_env`.
Nothing else from the tmux server's environment — `GITLAB_TOKEN`, `GITHUB_TOKEN`, cloud keys —
reaches it. The queue's `[env]` goes to the project commands, not to the agent. `pass_env` takes
names, never values.

**Write access to `.git` runs code outside the sandbox.** A worktree's `.git` points into the main
clone, and the agent needs to write there to commit. It can therefore add a hook
(`.git/hooks/…`) or config (`core.hooksPath`, `core.fsmonitor`, `alias.*`) that git will run
**unsandboxed** the next time you, the project commands or the runner run git in that clone. Treat
the clone as touched by the agent: review `git config --list --show-origin` and the hooks before
running git there outside the sandbox, or give each task its own clone.

### What the sandbox does not stop

- network services on the machine: the agent can reach anything listening on TCP, including
  `ssh localhost` with a key from the ssh-agent, and abstract unix sockets (for example X11's
  `@/tmp/.X11-unix/X0`), which live in the network namespace and cannot be hidden without
  cutting the network;
- the system D-Bus (`/run/dbus/system_bus_socket`) stays reachable; privileged actions there are
  guarded by polkit, not by the sandbox;
- what the agent writes into its own state (`~/.claude`, `~/.codex`) is kept and read by the next
  session of that agent, sandboxed or not;
- git hooks and config planted through `.git`, as described above.

Because the sandbox is the boundary, the agents run in their no-questions modes:
`claude --dangerously-skip-permissions`, `codex --dangerously-bypass-approvals-and-sandbox`.

`task-panes check` tells whether bwrap can start here. On Ubuntu 24.04 and later unprivileged user
namespaces are restricted by AppArmor, and bwrap works through the `bwrap-userns-restrict` profile
that ships with the `bubblewrap` package. If it cannot start, either allow it (that is a system
change for the machine's owner), or set `mode = "none"` and use the agents' own sandboxes instead:
Claude Code's sandbox settings, and
`codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true --add-dir DIR`.

`task-panes sandbox-run QUEUE --task T --agent A -- sh -c '...'` runs any command in exactly the
sandbox a task would get, to check what it can see and write.

## Setting it up from a chat

The `task-panes` skill is a setup wizard: ask your agent to set up a task queue, and it asks the
questions one at a time (tasks and where their dependencies come from, the completion check, the
working directory, the prompt, the agents, the session name, the number of panes), writes and
validates the file, shows the dry run and prints the commands. It never starts the runner — you do,
from a terminal.

## Licence

MIT.
