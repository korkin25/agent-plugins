"""Unit tests for task-panes: queue parsing, readiness, completion, recovery, agent choice, sandbox."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import tp_queue  # noqa: E402
import tp_runner  # noqa: E402
import tp_sandbox  # noqa: E402
import tp_tmux  # noqa: E402
from tp_tmux import LABEL_OPTION, TASK_OPTION, Pane  # noqa: E402

BIN = str(ROOT / "bin" / "task-panes")
DONE = ('if [ -f "$TP_QUEUE_DIR/done-$TP_ID" ]; then echo merged; exit 0; fi; '
        'if [ -f "$TP_QUEUE_DIR/fail-$TP_ID" ]; then echo pipeline failed; exit 2; fi; '
        'if [ -f "$TP_QUEUE_DIR/err-$TP_ID" ]; then echo api down; exit 5; fi; echo not merged; exit 1')


class FakeTmux:
    """In-memory tmux: panes live until killed; options are recorded."""

    def __init__(self):
        self.socket, self.exe = None, "tmux"
        self.sessions, self.store, self.splits, self.killed, self.count = set(), {}, [], [], 0
        self.parked = []

    def _new(self, argv, cwd, task=""):
        pane = f"%{self.count}"
        self.count += 1
        self.store[pane] = {"task": task, "argv": argv, "cwd": cwd, "label": ""}
        return pane

    def available(self):
        return True

    def has_session(self, session):
        return session in self.sessions

    def new_session(self, session, argv, cwd):
        self.sessions.add(session)
        return self._new(argv, cwd, "control")

    def split(self, target, argv, cwd, above=True):
        pane = self._new(argv, cwd)
        self.splits.append(pane)
        return pane

    def respawn(self, pane, argv, cwd):
        self.store[pane]["argv"] = argv

    def set_option(self, pane, key, value):
        self.store[pane]["task" if key == TASK_OPTION else "label"] = value

    def panes(self, session):
        if session not in self.sessions:
            return []
        return [Pane(p, d["task"], False) for p, d in self.store.items()]

    def park(self, pane, name):
        self.parked.append((pane, name))

    def kill_pane(self, pane):
        self.store.pop(pane, None)
        self.killed.append(pane)

    def kill_session(self, session):
        self.sessions.discard(session)
        self.store.clear()

    def layout(self, session, control, control_rows=8):
        pass


def queue_text(tasks: str, extra: str = "", agents: str = "") -> str:
    agents = agents or '[agents.fake]\ncommand = ["sh", "-c", "sleep 30", "{session_id}", "{prompt}"]\n'
    return textwrap.dedent(f"""\
        session = "t"
        panes = 2
        poll_seconds = 1
        worktree = "{{queue_dir}}/wt/{{slug}}"
        {extra}
        [commands]
        done = '{DONE}'
        [sandbox]
        mode = "none"
        """) + agents + textwrap.dedent(tasks)


THREE = """
[[tasks]]
id = "A"
title = "first"
[[tasks]]
id = "B"
title = "second"
depends_on = ["A"]
[[tasks]]
id = "C"
title = "third"
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tp-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.tmux = FakeTmux()

    def queue(self, text: str) -> tp_queue.Queue:
        path = self.dir / "queue.toml"
        path.write_text(text.replace("state_dir_here", str(self.dir / "state")), encoding="utf-8")
        queue = tp_queue.load(path)
        queue.state_dir = self.dir / "state"
        return queue

    def engine(self, queue) -> tp_runner.Engine:
        return tp_runner.Engine(queue, self.tmux, tp_runner.Store(queue.state_dir), BIN, out=lambda _: None)

    def mark(self, kind: str, task_id: str):
        (self.dir / f"{kind}-{task_id}").write_text("")

    def cycle(self, engine, rounds: int = 1):
        for _ in range(rounds):
            engine.heavy()
            engine.light()
            while engine.dirty:
                engine.dirty = False
                engine.heavy()
                engine.light()


class QueueParsingTest(Base):
    def test_defaults(self):
        path = self.dir / "q.toml"
        path.write_text(f'session = "s"\ntasks = ["X-1"]\n[commands]\ndone = "true"\n')
        queue = tp_queue.load(path)
        self.assertEqual(queue.panes, 2)
        self.assertEqual(sorted(queue.agents), ["claude", "codex"])
        self.assertIn("--session-id", queue.agents["claude"].command)
        self.assertEqual(queue.paths(queue.tasks[0]).slug, "x-1")
        self.assertEqual(queue.worktree_exists, "prepare")
        self.assertEqual(queue.sandbox.mode, "bwrap")

    def test_rejects_bad_files(self):
        cases = {
            'session = "s"\ntasks = ["A"]\n': "done is required",
            'session = "s"\nbogus = 1\ntasks = ["A"]\n[commands]\ndone = "true"\n': "unknown top-level",
            'session = "s"\ntasks = ["A", "A"]\n[commands]\ndone = "true"\n': "unique",
            'session = "s"\nprompt = "{nope}"\ntasks = ["A"]\n[commands]\ndone = "true"\n': "unknown placeholder",
            'session = "s"\n[[tasks]]\nid = "A"\ndepends_on = ["A"]\n[commands]\ndone = "true"\n': "itself",
            'session = "s"\npanes = 0\ntasks = ["A"]\n[commands]\ndone = "true"\n': "panes",
            'session = "s"\nworktree_exists = "maybe"\ntasks = ["A"]\n[commands]\ndone = "true"\n':
                "worktree_exists",
            'session = "s"\ntasks = ["A"]\n[commands]\ndone = "true"\n[sandbox]\nmode = "jail"\n': "sandbox.mode",
            'session = "s"\nagent = "x"\ntasks = ["A"]\n[commands]\ndone = "true"\n': "defines only",
            'session = "bad name"\ntasks = ["A"]\n[commands]\ndone = "true"\n': "session",
            'session = "s"\npass_env = ["A B"]\ntasks = ["A"]\n[commands]\ndone = "true"\n': "pass_env[0]",
            'session = "s"\ntasks = ["A"]\n[commands]\ndone = "true"\n[sandbox]\nhome_allow = "~/.x"\n':
                "home_allow",
        }
        for text, needle in cases.items():
            path = self.dir / "bad.toml"
            path.write_text(text)
            with self.subTest(needle=needle), self.assertRaises(tp_queue.QueueError) as ctx:
                tp_queue.load(path)
            self.assertIn(needle, str(ctx.exception))

    def test_missing_file_is_explained(self):
        with self.assertRaises(tp_queue.QueueError) as ctx:
            tp_queue.load(self.dir / "absent.toml")
        self.assertIn("not found", str(ctx.exception))


class TemplateTest(Base):
    def test_render_placeholders_and_braces(self):
        self.assertEqual(tp_queue.render("{a}-{{x}}", {"a": 1}), "1-{x}")
        with self.assertRaises(tp_queue.QueueError):
            tp_queue.render("{missing}", {})
        with self.assertRaises(tp_queue.QueueError):
            tp_queue.render("open { brace", {})

    def test_prompt_and_argv_substitution(self):
        queue = self.queue(queue_text("""
            [[tasks]]
            id = "ORCH-1"
            title = "Do it"
            slug = "{id_lower}-manual"
            branch = "feature/{slug}"
            ticket = 42
            extra_prompt = "Only for {id}."
            """, extra='prompt = "{id} {title} {slug} {worktree} {branch} {session_id} {ticket} {how}"',
            agents='[agents.fake]\ncommand = ["run", "--sid", "{session_id}", "{prompt}"]\n'
                   'prompt_prefix = "Read the rules first."\nvars = { how = "fresh" }\n'))
        task = queue.tasks[0]
        argv = queue.build_argv(task, "fake", "u-1")
        self.assertEqual(argv[:3], ["run", "--sid", "u-1"])
        wt = str(self.dir / "wt" / "orch-1-manual")
        self.assertEqual(argv[3], f"Read the rules first.\n\nORCH-1 Do it orch-1-manual {wt} "
                                  "feature/orch-1-manual u-1 42 fresh\n\nOnly for ORCH-1.")


class ReadinessTest(Base):
    def test_dependencies_and_done_codes(self):
        queue = self.queue(queue_text(THREE + '[[tasks]]\nid = "D"\n[[tasks]]\nid = "E"\n'))
        engine = self.engine(queue)
        self.mark("fail", "D")
        self.mark("err", "E")
        engine.dry = True
        engine.heavy()
        got = {r["id"]: (r["status"], r["reason"]) for r in engine.rows()}
        self.assertEqual(got["A"][0], "ready")
        self.assertEqual(got["B"], ("waiting", "waiting for A"))
        self.assertEqual(got["C"][0], "ready")
        self.assertEqual(got["D"], ("stopped", "completion check failed: pipeline failed"))
        self.assertEqual(got["E"], ("error", "completion check error: api down"))
        self.assertEqual(engine.would_start(), ["A", "C"])
        self.assertFalse((queue.state_dir / "state.json").exists(), "dry-run must not write state")

    def test_dependency_commands_from_the_project(self):
        extra_cmds = ('dependencies = \'if [ "$TP_ID" = B ]; then echo EXT-9; fi\'\n'
                      'dependency_done = \'test -f "$TP_QUEUE_DIR/dep-$TP_DEP"\'\n')
        text = queue_text(THREE).replace("[sandbox]", extra_cmds + "[sandbox]")
        queue = self.queue(text)
        engine = self.engine(queue)
        engine.dry = True
        engine.heavy()
        self.assertEqual(engine.evals["B"], ("waiting", "waiting for A, EXT-9"))
        self.mark("dep", "A")
        self.mark("dep", "EXT-9")
        engine.heavy()
        self.assertEqual(engine.evals["B"][0], "ready")


    def test_dependencies_command_not_ready_waits(self):
        extra_cmds = ('dependencies = \'if [ "$TP_ID" = C ]; then echo registry not synced; exit 1; fi; '
                      'if [ "$TP_ID" = A ]; then echo api down; exit 4; fi\'\n')
        queue = self.queue(queue_text(THREE).replace("[sandbox]", extra_cmds + "[sandbox]"))
        engine = self.engine(queue)
        engine.dry = True
        engine.heavy()
        self.assertEqual(engine.evals["C"], ("waiting", "registry not synced"))
        self.assertEqual(engine.evals["A"], ("error", "dependencies command: api down"))
        self.assertEqual(engine.would_start(), [])

class LifecycleTest(Base):
    def test_slots_done_closes_pane_and_starts_dependent(self):
        queue = self.queue(queue_text(THREE))
        engine = self.engine(queue)
        self.cycle(engine)
        running = {t: st["pane"] for t, st in engine.state["tasks"].items() if st["status"] == "running"}
        self.assertEqual(sorted(running), ["A", "C"])
        self.assertEqual(self.tmux.store[running["A"]]["argv"][2:4], ["_pane", "--state-dir"])
        self.mark("done", "A")
        self.cycle(engine)
        self.assertEqual(engine.status_of("A"), "done")
        self.assertIn(running["A"], self.tmux.killed)
        self.assertEqual(engine.status_of("B"), "running")
        self.assertEqual(json.loads((queue.state_dir / "verdict" / "A.json").read_text())["status"], "done")

    def test_agent_exit_without_done_stops_and_never_restarts(self):
        queue = self.queue(queue_text(THREE))
        engine = self.engine(queue)
        self.cycle(engine)
        pane = engine.state["tasks"]["A"]["pane"]
        engine.store.write_json(engine.store.file("exit", "A"), {"code": 0})
        engine.light()
        st = engine.state["tasks"]["A"]
        self.assertEqual(st["status"], "stopped")
        self.assertIn("agent exited (code 0), but the completion check says not done", st["reason"])
        self.assertEqual(st["pane"], pane, "the pane stays open with the explanation")
        verdict = json.loads(engine.store.file("verdict", "A").read_text())
        self.assertEqual(verdict["status"], "stopped")
        splits = len(self.tmux.splits)
        self.cycle(engine, rounds=3)
        self.assertEqual(len(self.tmux.splits), splits, "a stopped task is not relaunched")
        self.assertEqual(engine.status_of("A"), "stopped")
        self.assertEqual(engine.status_of("B"), "pending")

    def test_failed_check_while_running_keeps_the_slot_until_the_agent_leaves(self):
        queue = self.queue(queue_text(THREE + '[[tasks]]\nid = "D"\n'))
        engine = self.engine(queue)
        self.cycle(engine)
        self.mark("fail", "A")
        self.cycle(engine)
        st = engine.state["tasks"]["A"]
        self.assertEqual(st["status"], "stopped")
        self.assertIn(st["pane"], self.tmux.store)
        self.assertIn("STOPPED", self.tmux.store[st["pane"]]["label"])
        self.assertEqual(self.tmux.parked, [], "the agent still runs, so its pane stays in place")
        self.assertEqual(engine.status_of("D"), "pending")
        engine.store.write_json(engine.store.file("exit", "A"), {"code": 0})
        self.cycle(engine)
        self.assertEqual(self.tmux.parked, [(st["pane"], "A stopped")])
        self.assertEqual(engine.status_of("D"), "running")

    def test_stopped_pane_moves_to_its_own_window_and_frees_the_slot(self):
        queue = self.queue(queue_text(THREE + '[[tasks]]\nid = "D"\n'))
        engine = self.engine(queue)
        self.cycle(engine)
        pane = engine.state["tasks"]["A"]["pane"]
        engine.store.write_json(engine.store.file("exit", "A"), {"code": 1})
        self.cycle(engine)
        self.assertEqual(engine.status_of("A"), "stopped")
        self.assertEqual(self.tmux.parked, [(pane, "A stopped")])
        self.assertIn(pane, self.tmux.store, "the stopped pane stays open for the owner")
        self.assertNotIn(pane, self.tmux.killed)
        self.assertEqual(engine.status_of("D"), "running", "the next ready task takes the freed slot")
        self.assertEqual(engine.occupied(), 2)
        self.cycle(engine, rounds=2)
        self.assertEqual(len(self.tmux.parked), 1, "a parked pane is moved once")
        self.tmux.kill_pane(pane)
        self.cycle(engine)
        self.assertIsNone(engine.state["tasks"]["A"]["pane"])

    def test_runner_exits_once_every_task_is_done(self):
        queue = self.queue(queue_text(THREE))
        for task_id in ("A", "B", "C"):
            self.mark("done", task_id)
        said = []
        engine = tp_runner.Engine(queue, self.tmux, tp_runner.Store(queue.state_dir), BIN, out=said.append)
        calls = []
        code = tp_runner.serve(engine, stop_flag=lambda: calls.append(1) or len(calls) > 3)
        self.assertEqual(code, 0)
        self.assertTrue(any("all tasks are done; the runner exits" in line for line in said), said)
        self.assertLess(len(calls), 4, "the runner leaves by itself, not by the stop flag")

    def test_agent_env_is_only_the_pass_list_and_task_vars(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(GITLAB_TOKEN="secret-value", HOME="/nowhere", SSH_AUTH_SOCK="/s/agent",
                          PROJECT_HOST="gitlab.example")
        self.assertNotIn("GITLAB_TOKEN", tp_runner.PASS_ENV)
        queue = self.queue(queue_text(THREE, extra='pass_env = ["PROJECT_HOST", "NOT_SET_ANYWHERE"]'))
        engine = self.engine(queue)
        self.cycle(engine)
        env = json.loads(engine.store.file("launch", "A").read_text())["env"]
        expected = {"PATH", "HOME", "USER", "LOGNAME", "SSH_AUTH_SOCK", "LANG", "LC_ALL", "LC_CTYPE"}
        self.assertEqual({k for k in env if not k.startswith("TP_")},
                         (expected & set(os.environ)) | {"PROJECT_HOST"})
        self.assertNotIn("secret-value", json.dumps(env))

    def test_pass_env_takes_names_only(self):
        path = self.dir / "q.toml"
        path.write_text(queue_text(THREE, extra='pass_env = ["TOKEN=secret-value"]'))
        with self.assertRaises(tp_queue.QueueError) as ctx:
            tp_queue.load(path)
        self.assertIn("pass_env[0]", str(ctx.exception))
        self.assertNotIn("secret-value", str(ctx.exception))

    def test_restart_does_not_launch_a_live_task_twice(self):
        queue = self.queue(queue_text(THREE))
        first = self.engine(queue)
        self.cycle(first)
        splits = len(self.tmux.splits)
        second = self.engine(queue)
        self.cycle(second, rounds=2)
        self.assertEqual(len(self.tmux.splits), splits)
        self.assertEqual(second.status_of("A"), "running")

    def test_restart_verifies_a_task_whose_pane_vanished(self):
        queue = self.queue(queue_text(THREE))
        first = self.engine(queue)
        self.cycle(first)
        self.tmux.kill_pane(first.state["tasks"]["A"]["pane"])
        self.tmux.kill_pane(first.state["tasks"]["C"]["pane"])
        self.mark("done", "C")
        second = self.engine(queue)
        self.cycle(second)
        self.assertEqual(second.status_of("A"), "stopped")
        self.assertIn("agent pane closed", second.state["tasks"]["A"]["reason"])
        self.assertEqual(second.status_of("C"), "done")

    def test_reused_pane_id_is_not_mistaken_for_the_task(self):
        queue = self.queue(queue_text(THREE))
        engine = self.engine(queue)
        self.cycle(engine)
        pane = engine.state["tasks"]["A"]["pane"]
        self.tmux.store[pane]["task"] = "something-else"
        engine.light()
        self.assertEqual(engine.status_of("A"), "stopped")

    def test_reset_makes_a_stopped_task_startable(self):
        queue = self.queue(queue_text(THREE))
        engine = self.engine(queue)
        self.cycle(engine)
        engine.store.write_json(engine.store.file("exit", "A"), {"code": 1})
        engine.light()
        engine.store.write_json(engine.store.root / "resets" / "A.json", {"task": "A"})
        self.cycle(engine)
        self.assertEqual(engine.status_of("A"), "running")


class AgentChoiceTest(Base):
    AGENTS = ('[agents.one]\ncommand = ["sh", "-c", "sleep 30", "{prompt}"]\n'
              '[agents.two]\ncommand = ["sh", "-c", "sleep 31", "{prompt}"]\n')

    def test_task_field_fixes_the_agent(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\nagent = "two"\n', agents=self.AGENTS))
        engine = self.engine(queue)
        self.cycle(engine)
        self.assertEqual(engine.state["tasks"]["A"]["agent"], "two")

    def test_no_answer_means_no_start_while_others_run(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\n[[tasks]]\nid = "B"\nagent = "one"\n',
                                      agents=self.AGENTS))
        engine = self.engine(queue)
        self.cycle(engine, rounds=2)
        self.assertEqual(engine.status_of("A"), "pending")
        self.assertEqual(engine.evals["A"][0], "needs-agent")
        self.assertEqual(engine.status_of("B"), "running")
        self.assertEqual(engine.question().id, "A")

    def test_answer_from_the_control_pane_starts_the_task(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\n', agents=self.AGENTS))
        engine = self.engine(queue)
        self.cycle(engine)
        tp_runner.handle_input(engine, "2")
        engine.light()
        self.assertEqual(engine.status_of("A"), "running")
        self.assertEqual(engine.state["tasks"]["A"]["agent"], "two")
        record = json.loads(engine.store.file("launch", "A").read_text())
        self.assertEqual(record["argv"][:3], ["sh", "-c", "sleep 31"])

    def test_answer_file_from_the_cli(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\n', agents=self.AGENTS))
        engine = self.engine(queue)
        self.cycle(engine)
        engine.store.write_json(engine.store.root / "answers" / "A.json", {"task": "A", "agent": "one"})
        engine.light()
        self.assertEqual(engine.state["tasks"]["A"]["agent"], "one")
        self.assertTrue(engine.answer("A", "two").startswith("A is running"))
        self.assertIn("unknown agent", engine.answer("A", "nope"))


class WorktreeRuleTest(Base):
    TASKS = """
        [[tasks]]
        id = "A"
        worktree_exists = "resume"
        [[tasks]]
        id = "B"
        """

    def test_resume_launches_in_existing_worktree_and_stop_blocks(self):
        extra = 'worktree_exists = "stop"'
        text = queue_text(self.TASKS, extra=extra).replace(
            "[sandbox]", "prepare = 'touch \"$TP_QUEUE_DIR/prepared-$TP_ID\"; mkdir -p \"$TP_WORKTREE\"'\n[sandbox]")
        queue = self.queue(text)
        for slug in ("a", "b"):
            (self.dir / "wt" / slug).mkdir(parents=True)
        engine = self.engine(queue)
        self.cycle(engine)
        self.assertEqual(engine.status_of("A"), "running")
        self.assertFalse((self.dir / "prepared-A").exists(), "resume must not run prepare")
        self.assertEqual(self.tmux.store[engine.state["tasks"]["A"]["pane"]]["cwd"], str(self.dir / "wt" / "a"))
        self.assertEqual(engine.status_of("B"), "stopped")
        self.assertIn("worktree already exists", engine.state["tasks"]["B"]["reason"])

    def test_prepare_runs_for_a_new_worktree_and_failure_stops(self):
        text = queue_text(self.TASKS).replace(
            "[sandbox]", "prepare = 'if [ $TP_ID = B ]; then echo no branch >&2; exit 3; fi; "
                         "mkdir -p \"$TP_WORKTREE\"'\n[sandbox]")
        engine = self.engine(self.queue(text))
        self.cycle(engine)
        self.assertEqual(engine.status_of("A"), "running")
        self.assertEqual(engine.state["tasks"]["B"]["reason"], "prepare failed (exit 3): no branch")


def bound_over(args: list[str], path: Path) -> list[str]:
    """Bind targets in a bwrap argv, other than the read-only root, that are path or its parents."""
    return [args[i + 2] for i, a in enumerate(args[:-2]) if a in ("--bind", "--ro-bind")
            and args[i + 2] != "/" and path.is_relative_to(args[i + 2])]


class SandboxTest(Base):
    def test_plan_binds_hides_and_confines(self):
        home = self.dir / "home"
        for sub in (".claude", ".gnupg", "notes", ".mozilla", ".ssh", ".kube", ".config/git", ".config/gh",
                    ".config/tool", ".local/bin"):
            (home / sub).mkdir(parents=True)
        for name in (".claude.json", "vault.kdbx", ".gitconfig", ".ssh/config", ".ssh/known_hosts", ".ssh/id_x",
                     ".netrc", "notes/.env"):
            (home / name).write_text("")
        work = self.dir / "work"
        work.mkdir()
        runtime = self.dir / "run-user"
        (runtime / "gcr").mkdir(parents=True)
        (runtime / "gcr" / "ssh").write_text("")
        tmux_dir = self.dir / "tmux-tmp" / "tmux-1000"
        tmux_dir.mkdir(parents=True)
        env = {"XDG_RUNTIME_DIR": str(runtime), "SSH_AUTH_SOCK": str(runtime / "gcr" / "ssh"),
               "TMUX": f"{tmux_dir}/default,42,0", "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"}
        spec = tp_sandbox.SandboxSpec(writable=[str(self.dir / "evidence")], readonly=["~/notes"],
                                      hidden=["~/.secret-thing", "~/notes/.env"], tmpdir=str(self.dir / "scratch"),
                                      extra_args=["--unsetenv", "SOME_TOKEN"],
                                      home_allow=["~/.config/tool", "~/.absent-tool"])
        plan = tp_sandbox.plan(spec, ["~/.claude", "~/.claude.json", "~/.codex"], work, home=str(home),
                               env=env, tiocsti=False)
        args = plan.prefix
        joined = " ".join(args)
        self.assertEqual(args[:7], ["bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc",
                                    "--ro-bind", "/", "/"])
        self.assertIn("--dev-bind /dev /dev --tmpfs /dev/shm", joined, "/dev/shm is private")
        self.assertNotIn("--new-session", args, "the kernel already refuses TIOCSTI")
        self.assertIn(f"--tmpfs {runtime} ", joined)
        self.assertIn(f"--ro-bind {runtime / 'gcr' / 'ssh'} {runtime / 'gcr' / 'ssh'}", joined,
                      "the runtime dir is emptied and only the ssh-agent socket comes back")
        self.assertNotIn(f"--bind {runtime / 'gcr'} ", joined)
        self.assertTrue(f"--tmpfs {tmux_dir}" in joined or (tmux_dir.is_relative_to("/tmp") and "--tmpfs /tmp" in joined
                        and not bound_over(args, tmux_dir)), "the tmux server socket is out of reach")
        for name in ("DBUS_SESSION_BUS_ADDRESS", "TMUX", "TMUX_PANE"):
            self.assertIn(f"--unsetenv {name}", joined)
        self.assertIn(f"--tmpfs {home} ", joined, "$HOME starts empty")
        self.assertLess(args.index(str(home)), args.index(str(home / ".claude")), "binds land on the empty $HOME")
        self.assertIn(f"--bind {home / '.claude.json'} {home / '.claude.json'}", joined)
        self.assertIn(f"--bind {home / '.claude'} {home / '.claude'}", joined)
        self.assertIn(f"--ro-bind {home / 'notes'} {home / 'notes'}", joined)
        self.assertIn(f"--bind {work} {work}", joined)
        for allowed in (".gitconfig", ".config/git", ".ssh/config", ".ssh/known_hosts", ".local/bin",
                        ".config/tool"):
            self.assertIn(f"--ro-bind {home / allowed} {home / allowed}", joined, allowed)
        self.assertEqual(plan.home_allow, [home / p for p in (".gitconfig", ".config/git", ".ssh/config",
                                                              ".ssh/known_hosts", ".local/bin", ".config/tool")])
        for secret in (".ssh/id_x", ".kube", ".config/gh", ".netrc", ".gnupg", ".mozilla", "vault.kdbx",
                       ".absent-tool"):
            self.assertNotIn(str(home / secret), args, f"{secret} stays under the empty $HOME")
        self.assertNotIn(f"{home / '.ssh'} ", joined + " ", "only named files of ~/.ssh come back")
        self.assertIn(f"--ro-bind /dev/null {home / 'notes' / '.env'}", joined,
                      "a hidden path inside a bound directory is still hidden")
        self.assertIn("--tmpfs /tmp", joined)
        self.assertIn(f"--setenv TMPDIR {self.dir / 'scratch'}", joined)
        self.assertEqual(args[-5:-3], ["--unsetenv", "SOME_TOKEN"])
        self.assertEqual(args[-3:], ["--chdir", str(work), "--"])
        self.assertIn(self.dir / "evidence", plan.create)
        self.assertNotIn(home / ".codex", plan.writable, "absent agent state is not created")

    def test_ssh_agent_socket_returns_only_from_emptied_roots(self):
        home = self.dir / "home"
        (home / ".gnupg").mkdir(parents=True)
        (home / ".ssh").mkdir()
        gpg_sock = home / ".gnupg" / "S.gpg-agent.ssh"
        home_sock = home / ".ssh" / "agent.sock"
        plain = self.dir / "agent.sock"
        for sock in (gpg_sock, home_sock, plain):
            sock.write_text("")
        for sock, bound in ((gpg_sock, False), (home_sock, True), (plain, False)):
            env = {"XDG_RUNTIME_DIR": str(self.dir / "no-runtime"), "SSH_AUTH_SOCK": str(sock)}
            plan = tp_sandbox.plan(tp_sandbox.SandboxSpec(private_tmp=False), [], self.dir / "work",
                                   home=str(home), env=env, tiocsti=False)
            joined = " ".join(plan.prefix)
            with self.subTest(sock=sock.name):
                self.assertEqual(f"--ro-bind {sock} {sock}" in joined, bound,
                                 "the socket returns from the emptied $HOME, never from a hidden ~/.gnupg")
                self.assertNotIn(str(home / ".gnupg"), plan.prefix, "~/.gnupg is gone with $HOME")

    def test_home_is_always_emptied(self):
        home = self.dir / "home"
        (home / ".codex").mkdir(parents=True)
        plan = tp_sandbox.plan(tp_sandbox.SandboxSpec(hide_defaults=False, private_tmp=False),
                               ["~/.codex"], self.dir, home=str(home), env={})
        joined = " ".join(plan.prefix)
        self.assertIn(f"--tmpfs {home} ", joined)
        self.assertIn(f"--bind {home / '.codex'} {home / '.codex'}", joined)

    def test_tmux_socket_dir_is_emptied_unless_already_gone(self):
        home, runtime = self.dir / "home", self.dir / "run-user"
        home.mkdir()
        for tmux_dir, writable, emptied in ((self.dir / "sockets" / "tmux-1000", [], True),
                                            (runtime / "tmux-1000", [], False),
                                            (runtime / "tmux-1000", [str(runtime)], True)):
            tmux_dir.mkdir(parents=True, exist_ok=True)
            spec = tp_sandbox.SandboxSpec(private_tmp=False, writable=writable)
            env = {"XDG_RUNTIME_DIR": str(runtime), "TMUX": f"{tmux_dir}/default,42,0"}
            args = tp_sandbox.plan(spec, [], self.dir / "work", home=str(home), env=env, tiocsti=False).prefix
            with self.subTest(tmux_dir=str(tmux_dir), writable=writable):
                self.assertEqual(f"--tmpfs {tmux_dir}" in " ".join(args), emptied)
                if not emptied:
                    self.assertIn(f"--tmpfs {runtime}", " ".join(args), "already gone with the runtime dir")
                    self.assertEqual(bound_over(args, tmux_dir), [], "and no bind brings it back")

    def test_home_allow_never_turns_a_writable_path_read_only(self):
        home = self.dir / "home"
        for sub in (".claude", ".local/bin", ".config/tool"):
            (home / sub).mkdir(parents=True)
        spec = tp_sandbox.SandboxSpec(writable=["~/.local/bin", "~/.config/tool"], private_tmp=False,
                                      home_allow=["~/.claude", "~/.config/tool"])
        plan = tp_sandbox.plan(spec, ["~/.claude"], self.dir / "work", home=str(home), env={}, tiocsti=False)
        joined = " ".join(plan.prefix)
        for sub in (".claude", ".local/bin", ".config/tool"):
            path = home / sub
            with self.subTest(path=sub):
                self.assertIn(f"--bind {path} {path}", joined)
                self.assertNotIn(f"--ro-bind {path} {path}", joined, "a later --ro-bind would win in bwrap")
                self.assertNotIn(path, plan.home_allow)

    def test_tiocsti_and_daemon_sockets(self):
        sysctl = self.dir / "legacy_tiocsti"
        sysctl.write_text("0\n")
        self.assertFalse(tp_sandbox.tiocsti_allowed(str(sysctl)))
        sysctl.write_text("1\n")
        self.assertTrue(tp_sandbox.tiocsti_allowed(str(sysctl)))
        self.assertTrue(tp_sandbox.tiocsti_allowed(str(self.dir / "absent")))
        docker = self.dir / "run" / "docker.sock"
        docker.parent.mkdir()
        docker.write_text("")
        (self.dir / "var-run").symlink_to(docker.parent)
        saved = tp_sandbox.DEFAULT_HIDDEN_SYSTEM
        tp_sandbox.DEFAULT_HIDDEN_SYSTEM = [str(docker), str(self.dir / "var-run" / "docker.sock"),
                                            str(self.dir / "absent.sock")]
        self.addCleanup(setattr, tp_sandbox, "DEFAULT_HIDDEN_SYSTEM", saved)
        home = self.dir / "home"
        home.mkdir()
        plan = tp_sandbox.plan(tp_sandbox.SandboxSpec(), [], self.dir, home=str(home), env={}, tiocsti=True)
        joined = " ".join(plan.prefix)
        self.assertIn("--new-session", plan.prefix, "TIOCSTI allowed: the agent leaves the pane's session")
        self.assertEqual(joined.count("/dev/null"), 1, "a socket reached via a symlink is hidden once, at its target")
        self.assertIn(f"--ro-bind /dev/null {docker}", joined)
        self.assertNotIn("absent.sock", joined)
        plan = tp_sandbox.plan(tp_sandbox.SandboxSpec(hide_defaults=False), [], self.dir, home=str(home),
                               env={}, tiocsti=True)
        self.assertNotIn(str(docker), " ".join(plan.prefix))

    def test_tmux_socket_path(self):
        self.assertEqual(tp_tmux.socket_path(None, {"TMUX": "/s/x/default,1,0"}), "/s/x/default")
        self.assertEqual(tp_tmux.socket_path("smoke", {"TMUX": "/s/x/default,1,0", "TMUX_TMPDIR": "/v"}),
                         f"/v/tmux-{os.getuid()}/smoke")
        self.assertEqual(tp_tmux.socket_path(None, {}), f"/tmp/tmux-{os.getuid()}/default")

    def test_queue_sandbox_templates_are_rendered(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\n').replace(
            'mode = "none"', 'mode = "bwrap"\nwritable = ["/x/{slug}"]\ntmpdir = "/y/{session_id}/{slug}"\n'
                             'home_allow = ["~/.config/{agent}-tool"]'))
        spec = queue.sandbox_for(queue.tasks[0], "fake", "u-2")
        self.assertEqual((spec.writable, spec.tmpdir, spec.home_allow),
                         (["/x/a"], "/y/u-2/a", ["~/.config/fake-tool"]))

    def test_launch_wraps_the_agent_in_bwrap(self):
        queue = self.queue(queue_text('[[tasks]]\nid = "A"\n').replace(
            'mode = "none"', f'mode = "bwrap"\ntmpdir = "{self.dir}/tmp/{{slug}}"\nhide_defaults = false'))
        engine = self.engine(queue)
        self.cycle(engine)
        record = json.loads(engine.store.file("launch", "A").read_text())
        self.assertEqual(record["argv"][0], "bwrap")
        cut = record["argv"].index("--")
        self.assertEqual(record["argv"][cut + 1:cut + 3], ["sh", "-c"])
        self.assertEqual(oct((self.dir / "tmp" / "a").stat().st_mode & 0o777), "0o700")


class PaneAndCliTest(Base):
    def test_pane_starts_the_agent_from_the_launch_env_only(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(GITLAB_TOKEN="secret-value", TERM="tmux-256color")
        out_file = self.dir / "agent-env.json"
        store = tp_runner.Store(self.dir / "state")
        code = f"import json, os; json.dump(dict(os.environ), open({str(out_file)!r}, 'w'))"
        store.write_json(store.file("launch", "A"), {"id": "A", "title": "t", "agent": "fake", "session_id": "s",
                                                     "argv": [sys.executable, "-c", code], "cwd": str(self.dir),
                                                     "env": {"TP_ID": "A"}, "sandbox": "none"})
        store.write_json(store.file("verdict", "A"), {"status": "stopped", "reason": "not done"})
        saved_out, sys.stdout = sys.stdout, io.StringIO()
        try:
            tp_runner.pane_main(store.root, "A", stdin=io.StringIO("\n"))
        finally:
            sys.stdout = saved_out
        env = json.loads(out_file.read_text())
        self.assertNotIn("GITLAB_TOKEN", env, "the tmux server's environment does not reach the agent")
        self.assertEqual(env.get("TP_ID"), "A")
        self.assertEqual(env.get("TERM"), "tmux-256color")
        self.assertLessEqual(set(env) - {"TP_ID", "TERM", "COLORTERM"}, {"PWD", "LC_CTYPE"})

    def test_pane_reports_exit_and_holds_on_stop(self):
        store = tp_runner.Store(self.dir / "state")
        store.write_json(store.file("launch", "A"), {"id": "A", "title": "t", "agent": "fake", "session_id": "s",
                                                     "argv": ["sh", "-c", "exit 3"], "cwd": str(self.dir),
                                                     "env": {"TP_ID": "A"}, "sandbox": "none"})
        store.write_json(store.file("verdict", "A"), {"status": "stopped", "reason": "not done"})
        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            self.assertEqual(tp_runner.pane_main(store.root, "A", stdin=io.StringIO("\n")), 0)
        finally:
            sys.stdout = saved
        self.assertEqual(json.loads(store.file("exit", "A").read_text())["code"], 3)
        self.assertIn("STOPPED: not done", out.getvalue())

    def run_cli(self, *args):
        env = dict(os.environ, XDG_STATE_HOME=str(self.dir / "xdg"))
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, env=env,
                              stdin=subprocess.DEVNULL, timeout=60)

    def test_cli_without_arguments_explains(self):
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("choose a command", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_cli_dry_run_json_and_bad_queue(self):
        path = self.dir / "queue.toml"
        path.write_text(queue_text(THREE))
        proc = self.run_cli("dry-run", str(path), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["would_start"], ["A", "C"])
        self.assertFalse((self.dir / "xdg").exists(), "dry-run writes no state")
        path.write_text("session = 1\n")
        proc = self.run_cli("check", str(path))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("session must name", proc.stderr)

    def test_cli_sandbox_run_takes_options_after_queue(self):
        path = self.dir / "queue.toml"
        path.write_text(queue_text(THREE).replace('mode = "none"', 'mode = "bwrap"'))
        (self.dir / "wt-a").mkdir(exist_ok=True)
        proc = self.run_cli("sandbox-run", str(path), "--task", "A", "--cwd", str(self.dir / "wt-a"),
                            "--print", "--", "sh", "-c", "echo --task")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("bwrap "), proc.stdout)
        self.assertTrue(proc.stdout.rstrip().endswith("-- sh -c 'echo --task'"), proc.stdout)


if __name__ == "__main__":
    unittest.main()
