"""Synthetic tests for the bounded, fail-closed Codex turn metadata reader."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "lib"))
import router_runtime as runtime  # noqa: E402


def uuid7_at(when: datetime) -> str:
    return str(uuid.UUID(int=(int(when.timestamp() * 1000) << 80) | (7 << 76) | (0x8000 << 48) | 1))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir="/var/tmp", prefix="agent-plugins-runtime-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.session = uuid7_at(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        self.turn = str(uuid.uuid4())
        self.event = {"session_id": self.session, "turn_id": self.turn, "model": "gpt-6-astra"}

    def record(self, turn=None, model="gpt-6-astra", effort="high"):
        return {"type": "turn_context", "payload": {"turn_id": turn or self.turn, "model": model, "effort": effort}}

    def write(self, records, day="2026/09/25", name=None, mode=0o664):
        folder = self.root / "sessions" / day
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (name or "rollout-" + self.session + ".jsonl")
        path.write_text("\n".join(json.dumps(item) for item in records) + "\n")
        path.chmod(mode)
        return path

    def test_owner_group_writable_file_is_allowed(self):
        self.write([self.record()], mode=0o664)
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root),
                         {"model": "gpt-6-astra", "effort": "high", "source": "turn_context"})

    def test_exact_turn_and_model_required(self):
        self.write([self.record(turn=str(uuid.uuid4())), self.record(model="gpt-6-sol")])
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})
        self.assertEqual(runtime.resolve_codex_turn({**self.event, "turn_id": str(uuid.uuid4())}, self.root), {})

    def test_newer_invalid_exact_record_blocks_older_value(self):
        self.write([self.record(effort="low"), self.record(effort="inherit")])
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})

    def test_v7_day_window_and_unique_session_path(self):
        self.write([self.record()], day="2026/09/24")
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root)["effort"], "high")
        self.write([self.record()], day="2026/09/25")
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})

    def test_bad_owner_and_symlink_fail_closed(self):
        path = self.write([self.record()])
        with mock.patch.object(runtime.os, "geteuid", return_value=os.geteuid() + 1):
            self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})
        path.unlink()
        path.symlink_to("/etc/passwd")
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})

    def test_tail_bound_and_old_record_is_unknown(self):
        self.write([self.record(), {"type": "noise", "padding": "x" * (runtime._TAIL_BYTES + 10)}])
        self.assertEqual(runtime.resolve_codex_turn(self.event, self.root), {})
        original_read = os.read
        with mock.patch.object(runtime.os, "read", wraps=original_read) as read:
            runtime.resolve_codex_turn(self.event, self.root)
        self.assertLessEqual(read.call_args.args[1], runtime._TAIL_BYTES)

    def test_invalid_uuid_is_never_a_tree_fallback(self):
        self.write([self.record()])
        self.assertEqual(runtime.resolve_codex_turn({**self.event, "session_id": str(uuid.uuid4())}, self.root), {})
        self.assertEqual(runtime.resolve_codex_turn({**self.event, "session_id": "bad"}, self.root), {})


if __name__ == "__main__":
    unittest.main()
