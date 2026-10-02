"""The frozen task set in eval/taskset: its manifest matches the files, its spread meets the rule of the stage it
has reached, and every task's check fails untouched work, passes the solution and fails every broken variant."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

TASKSET = Path(__file__).resolve().parent.parent / "eval" / "taskset"

# The set grows in stages (README, "Stages"); a set at or past a stage's size meets that stage's spread:
# (size, domains it must cover or None for every domain, tasks per such domain, difficulties each such domain
# covers, tasks in Russian).
STAGES = [
    (50, {"math", "code", "debug", "text"}, 8, set(), 10),
    (190, None, 20, {1, 2, 3}, 19),
]
MAX_TASKS = 200


def load_module():
    spec = importlib.util.spec_from_file_location("taskset", TASKSET / "taskset.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


class TaskSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = load_module()
        cls.metas = [cls.ts.load(t) for t in cls.ts.task_ids()]

    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-B", str(TASKSET / "taskset.py"), *args],
                              capture_output=True, text=True, timeout=1800)

    def test_manifest_matches_the_files(self):
        proc = self.run_tool("manifest")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_size_and_spread(self):
        self.assertLessEqual(len(self.metas), MAX_TASKS)
        reached = [stage for stage in STAGES if len(self.metas) >= stage[0]]
        if not reached:
            return
        size, domains, per_domain, levels, russian = reached[-1]
        by_domain = Counter(m["domain"] for m in self.metas)
        for domain in sorted(domains) if domains else self.ts.DOMAINS:
            with self.subTest(stage=size, domain=domain):
                self.assertGreaterEqual(by_domain[domain], per_domain)
                self.assertLessEqual(levels, {m["difficulty"] for m in self.metas if m["domain"] == domain})
        with self.subTest(stage=size):
            self.assertEqual({m["difficulty"] for m in self.metas}, {1, 2, 3})
            self.assertGreaterEqual(sum(m["language"] == "ru" for m in self.metas), russian)

    def test_every_task_validates(self):
        jobs = os.environ.get("TASKSET_JOBS", str(min(4, os.cpu_count() or 1)))
        proc = self.run_tool("validate", "-j", jobs)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
