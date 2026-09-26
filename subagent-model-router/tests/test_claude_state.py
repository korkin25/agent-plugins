"""Offline lifecycle checkpoints: no user files, configuration, or transcripts."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import router_claude_state as state


class ClaudeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="router-claude-state-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "state"
        session = str(uuid.uuid4())
        self.event = dict(hook_event_name="SessionStart", session_id=session,
                          transcript_path=str(self.base / (session + ".jsonl")), model="claude-opus-4-6")

    def update(self, **changes):
        state.update_session(dict(self.event, **changes), self.root)

    def resolve(self, **changes):
        return state.resolve_session(dict(self.event, hook_event_name="PreToolUse", **changes), self.root)

    def slot(self):
        return self.root / state._slot(self.event["session_id"])

    def switch(self, **changes):
        self.update(**dict(dict(hook_event_name="PostModelSwitch", from_model="claude-opus-4-6",
                                to_model="claude-sonnet-4-6", source="picker"), **changes))

    def test_start_and_switch_and_duplicate(self):
        self.update()
        self.assertEqual(self.resolve(), {"model": "claude-opus-4-6", "source": "session_start"})
        self.switch()
        expected = {"model": "claude-sonnet-4-6", "source": "post_model_switch"}
        self.assertEqual(self.resolve(), expected)
        self.switch()
        self.assertEqual(self.resolve(), expected)

    def test_all_official_switch_sources(self):
        for source in ("command", "picker", "sdk", "auto", "resume"):
            with self.subTest(source=source):
                self.update()
                self.switch(source=source)
                self.assertEqual(self.resolve()["model"], "claude-sonnet-4-6")

    def test_start_invalidates_absent_or_invalid_model(self):
        for value in (None, "", "inherit", "bad model", {"model": "opus"}):
            with self.subTest(model=value):
                self.update()
                self.update(model=value, source="resume")
                self.assertEqual(self.resolve(), {})
        self.update()
        event = dict(self.event, source="resume")
        del event["model"]
        state.update_session(event, self.root)
        self.assertEqual(self.resolve(), {})

    def test_new_start_replaces_old_value(self):
        self.update()
        self.update(model="sonnet")
        self.assertEqual(self.resolve()["model"], "sonnet")

    def test_invalid_start_source_invalidates(self):
        self.update()
        self.update(source="invented")
        self.assertEqual(self.resolve(), {})

    def test_switch_mismatch_invalidates(self):
        self.update()
        self.switch(from_model="haiku")
        self.assertEqual(self.resolve(), {})

    def test_invalid_switch_fields_invalidate(self):
        for changes in (dict(to_model="bad model"), dict(to_model=None), dict(from_model=None), dict(source="invented")):
            with self.subTest(changes=changes):
                self.update()
                self.switch(**changes)
                self.assertEqual(self.resolve(), {})

    def test_switch_without_previous_checkpoint_is_direct_evidence(self):
        self.switch()
        self.assertEqual(self.resolve()["model"], "claude-sonnet-4-6")

    def test_end_invalidates(self):
        self.update()
        self.update(hook_event_name="SessionEnd")
        self.assertEqual(self.resolve(), {})

    def test_config_failure_invalidation_leaves_unknown_after_restore(self):
        self.update()
        # session_main invokes this when configuration is missing or invalid.
        state.invalidate_session(dict(self.event, source="resume"), self.root)
        self.assertEqual(self.resolve(), {})
        self.update()
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_invalidation_does_not_create_state(self):
        state.invalidate_session(self.event, self.root)
        self.assertFalse(self.root.exists())

    def test_invalidation_without_transcript_clears_uuid_slot(self):
        self.update()
        event = dict(self.event)
        del event["transcript_path"]
        state.invalidate_session(event, self.root)
        self.assertEqual(self.resolve(), {})

    def test_invalidation_rejects_nested_codex_and_non_lifecycle_events(self):
        self.update()
        for changes in (dict(agent_id="nested"), dict(turn_id=str(uuid.uuid4())),
                        dict(hook_event_name="PreToolUse"), dict(session_id="invalid"),
                        dict(transcript_path=str(self.base / ("rollout-" + self.event["session_id"] + ".jsonl")))):
            with self.subTest(changes=changes):
                state.invalidate_session(dict(self.event, **changes), self.root)
                self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_invalidation_other_session_preserves_noncolliding_checkpoint(self):
        self.update()
        second = str(uuid.uuid4())
        while state._slot(second) == self.slot().name:
            second = str(uuid.uuid4())
        other = dict(self.event, session_id=second, transcript_path=str(self.base / (second + ".jsonl")))
        state.invalidate_session(other, self.root)
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        with mock.patch.object(state, "_slot", return_value=self.slot().name):
            state.invalidate_session(other, self.root)
        self.assertEqual(self.resolve(), {})
        self.assertEqual(state.resolve_session(other, self.root), {})

    def test_unknown_lifecycle_event_cannot_change_checkpoint(self):
        self.update()
        self.update(hook_event_name="PreToolUse", model="haiku")
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_exact_scope_and_cross_session_isolation(self):
        self.update()
        self.assertEqual(self.resolve(session_id=str(uuid.uuid4())), {})
        self.assertEqual(self.resolve(transcript_path=self.event["transcript_path"] + ".other"), {})
        self.assertEqual(self.resolve(transcript_path="relative.jsonl"), {})
        self.assertEqual(self.resolve(session_id="invalid"), {})
        second = str(uuid.uuid4())
        while state._slot(second) == state._slot(self.event["session_id"]):
            second = str(uuid.uuid4())
        second_path = str(self.base / (second + ".jsonl"))
        self.update(session_id=second, transcript_path=second_path, model="haiku")
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        self.assertEqual(self.resolve(session_id=second, transcript_path=second_path)["model"], "haiku")

    def test_same_uuid_transcript_change_never_borrows_model(self):
        self.update()
        different = str(self.base / "other-project" / (self.event["session_id"] + ".jsonl"))
        self.update(transcript_path=different, model="haiku")
        self.assertEqual(self.resolve(), {})
        self.assertEqual(self.resolve(transcript_path=different)["model"], "haiku")

    def test_absent_invalid_transcript_update_invalidates(self):
        for transcript in (None, "", "relative", "bad\x00path"):
            self.update()
            self.update(transcript_path=transcript)
            self.assertEqual(self.resolve(), {})
        self.update()
        event = dict(self.event)
        del event["transcript_path"]
        state.update_session(event, self.root)
        self.assertEqual(self.resolve(), {})

    def test_subagent_and_codex_events_rejected(self):
        self.update()
        for changes in (dict(agent_id="nested"), dict(agent_id=None), dict(turn_id=str(uuid.uuid4()))):
            with self.subTest(changes=changes):
                self.assertEqual(self.resolve(**changes), {})
                self.update(model="haiku", **changes)
                self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_codex_rollout_path_cannot_supply_evidence(self):
        self.update()
        codex_path = str(self.base / ("rollout-2026-09-26-" + self.event["session_id"] + ".jsonl"))
        self.assertEqual(self.resolve(transcript_path=codex_path), {})
        self.update(transcript_path=codex_path, model="gpt-6")
        self.assertEqual(self.resolve(), {})

    def test_metadata_only_no_transcript_io_or_raw_event_retention(self):
        original_open = os.open
        opened = []
        def recording_open(path, *args, **kwargs):
            opened.append(str(path))
            return original_open(path, *args, **kwargs)
        with mock.patch.object(state.os, "open", side_effect=recording_open):
            self.update(prompt="private-dialogue", output="private-output", cwd="/private-project")
            self.resolve()
        raw = self.slot().read_text()
        for secret in ("private-dialogue", "private-output", "private-project", self.event["transcript_path"]):
            self.assertNotIn(secret, raw)
        self.assertNotIn(self.event["transcript_path"], opened)
        self.assertEqual(self.slot().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_stale_future_and_invalid_timestamp_rejected(self):
        self.update()
        for stamp in (time.time() - state.TTL_SECONDS - 1, time.time() + 60, True, "today", float("nan")):
            record = json.loads(self.slot().read_text())
            record["updated"] = stamp
            self.slot().write_text(json.dumps(record))
            self.assertEqual(self.resolve(), {})

    def test_corruption_and_oversized_state_rejected(self):
        self.update()
        for data in ("{", "[]", '"string"', "[" * 1000 + "]" * 1000, "x" * (state.MAX_BYTES + 1)):
            self.slot().write_text(data)
            self.assertEqual(self.resolve(), {})

    def test_symlink_file_and_ancestor_rejected(self):
        self.update()
        target = self.base / "target"
        target.write_text(self.slot().read_text())
        self.slot().unlink()
        self.slot().symlink_to(target)
        self.assertEqual(self.resolve(), {})
        self.update(model="haiku")
        self.assertEqual(json.loads(target.read_text())["model"], "claude-opus-4-6")
        link = self.base / "link"
        link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(state.resolve_session(self.event, link), {})
        state.update_session(self.event, link / "child")
        self.assertFalse((self.root / "child").exists())

    def test_wrong_owner_and_writable_state_rejected(self):
        self.update()
        with mock.patch.object(state.os, "geteuid", return_value=os.geteuid() + 1):
            self.assertEqual(self.resolve(), {})
        self.slot().chmod(0o660)
        self.assertEqual(self.resolve(), {})
        self.slot().chmod(0o600)
        self.root.chmod(0o770)
        self.assertEqual(self.resolve(), {})

    def test_hardlink_rejected(self):
        self.update()
        os.link(self.slot(), self.base / "copy")
        self.assertEqual(self.resolve(), {})

    def test_read_and_lock_are_bounded(self):
        self.update()
        with mock.patch.object(state.os, "read", wraps=os.read) as read:
            self.resolve()
        self.assertEqual(len(read.call_args_list), 1)
        self.assertLessEqual(read.call_args.args[1], state.MAX_BYTES + 1)
        with self.slot().open("rb") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            start = time.monotonic()
            self.assertEqual(self.resolve(), {})
            self.switch()
            self.assertLess(time.monotonic() - start, 1)
            self.assertFalse(self.slot().exists())
        self.assertEqual(self.resolve(), {})

    def test_failed_write_and_truncate_never_leave_old_evidence(self):
        for operation in ("write", "ftruncate", "fsync"):
            with self.subTest(operation=operation):
                self.update()
                with mock.patch.object(state.os, operation, side_effect=OSError("synthetic failure")):
                    self.switch()
                self.assertEqual(self.resolve(), {})

    def test_short_write_invalidates(self):
        self.update()
        with mock.patch.object(state.os, "write", return_value=1):
            self.switch()
        self.assertEqual(self.resolve(), {})

    def test_slot_collision_loses_evidence_and_bounds_file_count(self):
        with mock.patch.object(state, "MAX_SLOTS", 2):
            self.update()
            for _ in range(20):
                session = str(uuid.uuid4())
                self.update(session_id=session, transcript_path=str(self.base / (session + ".jsonl")), model="haiku")
            self.assertLessEqual(len(list(self.root.iterdir())), 2)
            # Force a known collision rather than depend on random occupancy.
            with mock.patch.object(state, "_slot", return_value=self.slot().name):
                self.update(session_id=session, transcript_path=str(self.base / (session + ".jsonl")), model="haiku")
            self.assertEqual(self.resolve(), {})

    def test_xdg_default_is_isolated_and_relative_root_rejected(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.base / "xdg")}):
            state.update_session(self.event)
            self.assertEqual(state.resolve_session(self.event)["model"], "claude-opus-4-6")
        self.assertTrue((self.base / "xdg/subagent-model-router/claude-sessions").is_dir())
        self.assertEqual(state.resolve_session(self.event, "relative"), {})


if __name__ == "__main__":
    unittest.main()
