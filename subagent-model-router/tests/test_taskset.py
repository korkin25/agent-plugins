"""The frozen task set in eval/taskset: its manifest matches the files, its spread covers every domain and
difficulty, and every task's check fails untouched work, passes the solution and fails every broken variant."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

TASKSET = Path(__file__).resolve().parent.parent / "eval" / "taskset"


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
        self.assertGreaterEqual(len(self.metas), 100)
        self.assertLessEqual(len(self.metas), 200)
        by_domain = Counter(m["domain"] for m in self.metas)
        for domain in self.ts.DOMAINS:
            with self.subTest(domain=domain):
                self.assertGreaterEqual(by_domain[domain], 8)
                levels = {m["difficulty"] for m in self.metas if m["domain"] == domain}
                self.assertEqual(levels, {1, 2, 3})
        self.assertGreaterEqual(sum(m["language"] == "ru" for m in self.metas), 8)

    def test_every_task_validates(self):
        jobs = os.environ.get("TASKSET_JOBS", str(min(4, os.cpu_count() or 1)))
        proc = self.run_tool("validate", "-j", jobs)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
