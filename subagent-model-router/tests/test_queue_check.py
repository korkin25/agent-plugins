"""queues/queue_check.py decides when a queue task is done and cleans up after it; queues/p0.toml is a valid queue
whose tasks name real TODO items."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROUTER = Path(__file__).resolve().parent.parent
QUEUES = ROUTER / "queues"
TASK_PANES_LIB = ROUTER.parent / "task-panes" / "lib"


def load_module():
    spec = importlib.util.spec_from_file_location("queue_check", QUEUES / "queue_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qc = load_module()

TODO_TEXT = """# TODO

- [ ] **Open item.**
- [x] **Closed item.**
- [ ] **Another open item.**
"""


def manifest(count: int) -> str:
    return json.dumps({"version": 1, "tasks": {f"t-{i:02d}": "0" * 64 for i in range(count)}})


class GitFixture(unittest.TestCase):
    """A bare origin and a clone of it; queue_check works on the clone and never on the network."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        empty = self.tmp / "gitconfig"
        empty.write_text("")
        self.enterContext(mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "XDG_CACHE_HOME": str(self.tmp / "cache"),
        }))
        self.origin = self.tmp / "origin.git"
        self.repo = self.tmp / "repo"
        self.run_git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(self.origin))
        self.run_git(self.tmp, "clone", "--quiet", str(self.origin), str(self.repo))
        self.enterContext(mock.patch.object(qc, "REPO", self.repo))
        self.ci = {}  # sha -> (state, detail); missing means pending
        self.fetches = []
        self.enterContext(mock.patch.object(qc, "fetch_runs", self.fake_runs))
        self.commit({qc.TODO: TODO_TEXT, qc.MANIFEST: manifest(1)}, "start")

    def fake_runs(self, sha):
        self.fetches.append(sha)
        return self.ci.get(sha, ("pending", "no workflow runs on main yet"))

    def run_git(self, cwd, *args):
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def commit(self, files: dict[str, str], message: str, push: bool = True) -> str:
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.run_git(self.repo, "add", "-A")
        self.run_git(self.repo, "commit", "--quiet", "--allow-empty", "-m", message)
        if push:
            self.run_git(self.repo, "push", "--quiet", "origin", "HEAD:main")
            self.run_git(self.repo, "fetch", "--quiet", "origin")
        return self.run_git(self.repo, "rev-parse", "HEAD")

    def done(self, task_id: str, **fields) -> tuple[int, str]:
        env = {"TP_ID": task_id, **{f"TP_FIELD_{k.upper()}": str(v) for k, v in fields.items()}}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            code = qc.cmd_done()
        return code, out.getvalue().strip().splitlines()[-1]


class QueueDoneTests(GitFixture):
    def test_a_task_without_a_merge_is_not_done(self):
        code, reason = self.done("P0-01")
        self.assertEqual(code, 1)
        self.assertIn("Queue-Task: P0-01", reason)

    def test_the_marker_must_be_an_exact_line(self):
        self.commit({}, "Merge p0/x\n\nQueue-Task: P0-10")
        self.commit({}, "Merge p0/y\n\nmentions Queue-Task: P0-1 inline")
        with self.assertRaises(qc.NotYet):
            qc.merge_commit("P0-1")
        self.assertTrue(qc.merge_commit("P0-10"))

    def test_only_the_first_parent_line_counts(self):
        """A marker on a branch commit that a merge brought in is not the task's merge: CI ran on the merge."""
        self.run_git(self.repo, "switch", "--quiet", "-c", "side")
        self.commit({"side.txt": "x"}, "work\n\nQueue-Task: P0-01", push=False)
        self.run_git(self.repo, "switch", "--quiet", "main")
        self.run_git(self.repo, "merge", "--quiet", "--no-ff", "side", "-m", "Merge side")
        self.run_git(self.repo, "push", "--quiet", "origin", "HEAD:main")
        self.run_git(self.repo, "fetch", "--quiet", "origin")
        with self.assertRaises(qc.NotYet):
            qc.merge_commit("P0-01")

    def test_a_replace_ref_cannot_forge_a_merge(self):
        """The sandbox leaves .git writable: refs/replace could show a green commit with a forged message and TODO."""
        base = self.run_git(self.repo, "rev-parse", "HEAD")
        sha = self.commit({"x.txt": "x"}, "An ordinary commit")
        self.ci[sha] = ("success", "green")
        self.run_git(self.repo, "switch", "--quiet", "--detach", base)
        forged = self.commit({qc.TODO: TODO_TEXT.replace("- [ ] **Open item.**", "- [x] **Open item.**")},
                             "Merge\n\nQueue-Task: P0-01", push=False)
        self.run_git(self.repo, "replace", sha, forged)
        self.assertIn("Queue-Task: P0-01", self.run_git(self.repo, "log", "-1", "--format=%B", "origin/main"))
        code, reason = self.done("P0-01", todo="Open item.")
        self.assertEqual(code, 1, reason)
        self.assertIn("not merged", reason)

    def test_a_marker_on_an_unpushed_commit_does_not_count(self):
        self.commit({}, "Merge\n\nQueue-Task: P0-01", push=False)
        self.assertEqual(self.done("P0-01")[0], 1)

    def test_a_merged_task_with_green_ci_is_done(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: P0-01")
        self.ci[sha] = ("success", "3 check runs green")
        code, reason = self.done("P0-01")
        self.assertEqual(code, 0, reason)
        self.assertIn(sha[:12], reason)

    def test_pending_and_failed_ci_are_not_done(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: P0-01")
        code, reason = self.done("P0-01")
        self.assertEqual((code, "no workflow runs" in reason), (1, True))
        qc.cache_dir().joinpath(f"{sha}.json").unlink()
        self.ci[sha] = ("failure", "not green: validate (failure)")
        code, reason = self.done("P0-01")
        self.assertEqual(code, 1)
        self.assertIn("merge again", reason)

    def test_the_newest_marker_counts(self):
        first = self.commit({}, "Merge\n\nQueue-Task: P0-01")
        second = self.commit({}, "Merge again\n\nQueue-Task: P0-01")
        self.ci[first] = ("failure", "not green: validate (failure)")
        self.ci[second] = ("success", "green")
        self.assertEqual(self.done("P0-01")[0], 0)
        self.assertEqual(self.fetches, [second])

    def test_the_todo_item_must_be_checked(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: P0-01")
        self.ci[sha] = ("success", "green")
        code, reason = self.done("P0-01", todo="Open item.")
        self.assertEqual(code, 1)
        self.assertIn("not checked", reason)
        self.assertEqual(self.done("P0-01", todo="Closed item.")[0], 0)

    def test_a_missing_todo_item_is_a_broken_setup(self):
        self.commit({}, "Merge\n\nQueue-Task: P0-01")
        code, reason = self.done("P0-01", todo="No such item.")
        self.assertEqual(code, 2)
        self.assertIn("no item", reason)

    def test_the_task_set_must_reach_min_tasks(self):
        sha = self.commit({qc.MANIFEST: manifest(9)}, "Merge\n\nQueue-Task: P0-01")
        self.ci[sha] = ("success", "green")
        code, reason = self.done("P0-01", min_tasks=10)
        self.assertEqual(code, 1)
        self.assertIn("lists 9 tasks", reason)
        sha = self.commit({qc.MANIFEST: manifest(10)}, "Merge\n\nQueue-Task: P0-01")
        self.ci[sha] = ("success", "green")
        self.assertEqual(self.done("P0-01", min_tasks=10)[0], 0)
        self.assertEqual(self.done("P0-01", min_tasks="ten")[0], 2)
        self.commit({qc.MANIFEST: "[]"}, "Merge\n\nQueue-Task: P0-01")
        code, reason = self.done("P0-01", min_tasks=10)
        self.assertEqual(code, 1)
        self.assertIn("no `tasks` object", reason)

    def test_without_tp_id_the_setup_is_broken(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TP_ID", None)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(qc.cmd_done(), 2)

    def test_a_green_answer_is_cached_for_good_and_others_for_a_while(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: P0-01")
        self.assertEqual(qc.ci_state(sha)[0], "pending")
        self.assertEqual(qc.ci_state(sha)[0], "pending")
        self.assertEqual(len(self.fetches), 1)
        self.ci[sha] = ("success", "green")
        with mock.patch.object(qc, "PENDING_TTL", 0):
            self.assertEqual(qc.ci_state(sha)[0], "success")
            self.assertEqual(qc.ci_state(sha)[0], "success")
        self.assertEqual(len(self.fetches), 2)
        mode = qc.cache_dir().stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)


class WorkflowRunsTests(unittest.TestCase):
    """fetch_runs reads GitHub's workflow runs for a commit; the network is replaced by canned answers."""

    def answer(self, runs, total=None):
        data = {"total_count": len(runs) if total is None else total, "workflow_runs": runs}
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        with mock.patch.object(qc, "github_repo", return_value="owner/repo"), \
                mock.patch.object(qc.urllib.request, "urlopen", return_value=response) as urlopen:
            result = qc.fetch_runs("abc123")
        self.assertIn("/repos/owner/repo/actions/runs?head_sha=abc123", urlopen.call_args[0][0].full_url)
        return result

    @staticmethod
    def run_(workflow, run_id, status="completed", conclusion="success", branch="main"):
        return {"name": f"wf{workflow}", "workflow_id": workflow, "id": run_id, "status": status,
                "conclusion": conclusion, "head_branch": branch}

    def test_all_green(self):
        runs = [self.run_(1, 10), self.run_(2, 11, conclusion="skipped"), self.run_(3, 12, conclusion="neutral")]
        self.assertEqual(self.answer(runs), ("success", "3 workflow runs green"))

    def test_no_run_or_an_unfinished_one_is_pending(self):
        self.assertEqual(self.answer([])[0], "pending")
        for status in ("queued", "pending", "waiting", "in_progress"):
            with self.subTest(status=status):
                runs = [self.run_(1, 10), self.run_(2, 11, status, None)]
                self.assertEqual(self.answer(runs), ("pending", "running: wf2"))

    def test_a_failed_or_cancelled_run_is_not_green(self):
        self.assertEqual(self.answer([self.run_(1, 10, conclusion="failure")])[0], "failure")
        state, detail = self.answer([self.run_(1, 10), self.run_(2, 11, conclusion="cancelled")])
        self.assertEqual(state, "failure")
        self.assertIn("wf2 (cancelled)", detail)

    def test_the_newest_run_of_a_workflow_counts(self):
        runs = [self.run_(1, 11), self.run_(1, 10, conclusion="failure")]
        self.assertEqual(self.answer(runs)[0], "success")
        runs = [self.run_(1, 10), self.run_(1, 11, conclusion="failure")]
        self.assertEqual(self.answer(runs)[0], "failure")

    def test_runs_of_other_branches_do_not_count(self):
        self.assertEqual(self.answer([self.run_(1, 10, branch="p0/x")])[0], "pending")
        runs = [self.run_(1, 10), self.run_(2, 11, conclusion="failure", branch="p0/x")]
        self.assertEqual(self.answer(runs)[0], "success")

    def test_more_than_a_page_is_unknown(self):
        self.assertEqual(self.answer([self.run_(1, 10)], total=101)[0], "unknown")

    def test_an_unreachable_api_or_a_strange_answer_is_unknown(self):
        with mock.patch.object(qc, "github_repo", return_value="owner/repo"), \
                mock.patch.object(qc.urllib.request, "urlopen", side_effect=urllib.error.URLError("down")):
            self.assertEqual(qc.fetch_runs("abc123")[0], "unknown")
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(b'{"message": "API rate limit exceeded"}')
        with mock.patch.object(qc, "github_repo", return_value="owner/repo"), \
                mock.patch.object(qc.urllib.request, "urlopen", return_value=response):
            self.assertEqual(qc.fetch_runs("abc123")[0], "unknown")

    def test_the_repository_comes_from_origin(self):
        for url in ("git@github.com:korkin25/agent-plugins.git", "https://github.com/korkin25/agent-plugins",
                    "https://github.com/korkin25/agent-plugins.git"):
            proc = subprocess.CompletedProcess([], 0, stdout=url + "\n", stderr="")
            with mock.patch.object(qc, "git", return_value=proc):
                self.assertEqual(qc.github_repo(), "korkin25/agent-plugins")
        proc = subprocess.CompletedProcess([], 0, stdout="/srv/repo.git\n", stderr="")
        with mock.patch.object(qc, "git", return_value=proc), self.assertRaises(qc.Broken):
            qc.github_repo()


class PruneTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.temp_root = self.tmp / "vartmp"
        self.temp_root.mkdir()
        self.enterContext(mock.patch.object(qc, "TEMP_ROOT", self.temp_root))
        self.session = self.temp_root / "agent-plugins-q"
        self.queue = self.tmp / "q.toml"
        self.state = self.tmp / "state"
        self.queue.write_text(f"""
session = "q"
state_dir = "{self.state}"
slug = "{{id_lower}}"
worktree = "{self.temp_root}/agent-plugins-{{session}}/{{slug}}/wt"
branch = "q/{{slug}}"
[commands]
done = "true"
[[tasks]]
id = "T1"
[[tasks]]
id = "T2"
[[tasks]]
id = "T3"
[[tasks]]
id = "T4"
""")

    def runner_state(self, **tasks: dict) -> None:
        """state.json as the runner writes it: a done task has its pane closed."""
        self.state.mkdir(exist_ok=True)
        (self.state / "state.json").write_text(json.dumps({"tasks": tasks}))

    def worktree(self, slug: str) -> Path:
        path = self.session / slug / "wt"
        (path.parent / "tmp").mkdir(parents=True)
        self.run_git(self.repo, "worktree", "add", "--quiet", "-b", f"q/{slug}", str(path), "origin/main")
        return path

    def prune(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(qc.cmd_prune(str(self.queue)), 0)
        return out.getvalue()

    def test_only_a_done_clean_and_merged_task_is_removed(self):
        for task in ("T1", "T2", "T3"):
            sha = self.commit({}, f"Merge\n\nQueue-Task: {task}")
            self.ci[sha] = ("success", "green")
        self.runner_state(**{t: {"status": "done", "pane": None} for t in ("T1", "T2", "T3", "T4")})
        done_clean, dirty, unmerged, not_done = (self.worktree(s) for s in ("t1", "t2", "t3", "t4"))
        (dirty / "notes.txt").write_text("work in progress")
        (unmerged / "extra.txt").write_text("x")
        self.run_git(unmerged, "add", "extra.txt")
        self.run_git(unmerged, "commit", "--quiet", "-m", "not merged")

        report = self.prune()

        self.assertFalse((self.session / "t1").exists(), report)
        self.assertEqual(self.run_git(self.repo, "branch", "--list", "q/t1"), "")
        self.assertIn("T2: kept", report)
        self.assertIn("uncommitted changes", report)
        self.assertIn("T3: kept", report)
        self.assertIn("commits not on origin/main", report)
        self.assertNotIn("T4", report)
        for path in (dirty, unmerged, not_done):
            self.assertTrue(path.is_dir())

    def test_a_commit_on_a_detached_head_is_kept(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: T1")
        self.ci[sha] = ("success", "green")
        self.runner_state(T1={"status": "done", "pane": None})
        path = self.worktree("t1")
        self.run_git(path, "switch", "--quiet", "--detach")
        (path / "late.txt").write_text("x")
        self.run_git(path, "add", "late.txt")
        self.run_git(path, "commit", "--quiet", "-m", "after the merge")
        report = self.prune()
        self.assertIn("T1: kept", report)
        self.assertIn("worktree's HEAD has commits not on origin/main", report)
        self.assertTrue((path / "late.txt").is_file())

    def test_a_task_the_runner_has_not_closed_is_untouched(self):
        """dry-run and status run refresh too: a merged task whose pane is open, or that the runner has not
        recorded as done, keeps its worktree."""
        sha = self.commit({}, "Merge\n\nQueue-Task: T1")
        self.ci[sha] = ("success", "green")
        sha = self.commit({}, "Merge\n\nQueue-Task: T2")
        self.ci[sha] = ("success", "green")
        paths = [self.worktree("t1"), self.worktree("t2"), self.worktree("t3")]
        self.assertEqual(self.prune(), "")  # no state.json at all
        self.runner_state(T1={"status": "running", "pane": "%3"}, T2={"status": "done", "pane": "%4"},
                          T3={"status": "done", "pane": None})
        self.assertEqual(self.prune(), "")  # T3 is not merged
        for path in paths:
            self.assertTrue(path.is_dir())

    def test_the_session_directory_goes_with_its_last_task(self):
        sha = self.commit({}, "Merge\n\nQueue-Task: T1")
        self.ci[sha] = ("success", "green")
        self.runner_state(T1={"status": "done", "pane": None})
        self.worktree("t1")
        self.prune()
        self.assertFalse(self.session.exists())
        self.assertTrue(self.temp_root.is_dir())

    def test_a_directory_outside_the_temp_root_is_never_deleted(self):
        paths = mock.Mock()
        for worktree, slug, expected in (
            (self.session / "t1" / "wt", "t1", self.session / "t1"),
            (self.tmp / "elsewhere" / "s" / "t1" / "wt", "t1", None),
            (self.session / "other" / "wt", "t1", None),
            (self.temp_root / "t1" / "wt", "t1", None),
        ):
            with self.subTest(worktree=worktree):
                paths.worktree, paths.slug = worktree, slug
                self.assertEqual(qc.task_dir(paths), expected and expected.resolve())

        sha = self.commit({}, "Merge\n\nQueue-Task: T1")
        self.ci[sha] = ("success", "green")
        self.runner_state(T1={"status": "done", "pane": None})
        outside = self.tmp / "elsewhere" / "q" / "t1" / "wt"
        self.queue.write_text(self.queue.read_text().replace(f"{self.temp_root}/agent-plugins-{{session}}",
                                                             f"{self.tmp}/elsewhere/{{session}}"))
        (outside.parent / "tmp").mkdir(parents=True)
        self.run_git(self.repo, "worktree", "add", "--quiet", "-b", "q/t1", str(outside), "origin/main")
        report = self.prune()
        self.assertIn(f"not in a task directory below {self.temp_root}", report)
        self.assertTrue(outside.is_dir())
        self.assertIn(str(outside), self.run_git(self.repo, "worktree", "list"))


class P0QueueTests(unittest.TestCase):
    """queues/p0.toml loads, renders for every task and agent, and refers to real TODO items."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TASK_PANES_LIB))
        import tp_queue
        cls.tp_queue = tp_queue
        cls.queue = tp_queue.load(QUEUES / "p0.toml")
        cls.todo = (ROUTER / "TODO.md").read_text()

    def test_every_task_names_a_todo_item(self):
        for task in self.queue.tasks:
            with self.subTest(task=task.id):
                # An item stays an item once a task checks it.
                self.assertRegex(self.todo, rf"- \[[ xX]\] \*\*{re.escape(task.fields['todo'])}\*\*")

    def test_every_p0_item_is_a_task(self):
        p0 = self.todo.split("## P0", 1)[1].split("\n## ", 1)[0]
        items = [line.split("**")[1] for line in p0.splitlines() if line.startswith("- [")]
        self.assertCountEqual(items, [t.fields["todo"] for t in self.queue.tasks])

    def test_dependencies_exist_and_have_no_cycle(self):
        ids = {t.id for t in self.queue.tasks}
        order = []
        pending = {t.id: set(t.depends_on) for t in self.queue.tasks}
        for deps in pending.values():
            self.assertLessEqual(deps, ids)
        while pending:
            ready = [i for i, deps in pending.items() if deps <= set(order)]
            self.assertTrue(ready, f"a dependency cycle among {sorted(pending)}")
            order += sorted(ready)
            for i in ready:
                del pending[i]

    def test_paths_are_unique_and_prune_can_remove_them(self):
        paths = [self.queue.paths(t) for t in self.queue.tasks]
        self.assertEqual(len({p.branch for p in paths}), len(paths))
        self.assertEqual(len({p.worktree for p in paths}), len(paths))
        for p in paths:
            with self.subTest(slug=p.slug):
                self.assertEqual(p.worktree.parent.name, p.slug)
                self.assertEqual(p.worktree.parent.parent.parent, qc.TEMP_ROOT)

    def test_prompts_and_sandboxes_render_for_every_agent(self):
        for task in self.queue.tasks:
            for agent in self.queue.agents:
                with self.subTest(task=task.id, agent=agent):
                    prompt = self.queue.build_prompt(task, agent, "sid")
                    self.assertIn(f"Queue-Task: {task.id}", prompt)
                    self.assertIn(task.fields["todo"], prompt)
                    self.queue.build_argv(task, agent, "sid")
                    self.queue.sandbox_for(task, agent, "sid")

    def test_stage_sizes_match_the_task_set_rule(self):
        path = Path(__file__).with_name("test_taskset.py")
        spec = importlib.util.spec_from_file_location("test_taskset_stages", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sizes = [int(t.fields["min_tasks"]) for t in self.queue.tasks if "min_tasks" in t.fields]
        self.assertEqual(sizes, [stage[0] for stage in module.STAGES])


if __name__ == "__main__":
    unittest.main()
