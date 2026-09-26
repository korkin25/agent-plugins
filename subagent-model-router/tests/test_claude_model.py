"""Synthetic-only tests of the opt-in exact Claude initiating-model reader."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import uuid

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "lib"))
import router_claude_model as reader  # noqa: E402


class ClaudeModelTests(unittest.TestCase):
    def setUp(self):
        # Honor the runner's TMPDIR; canonicalize only our synthetic fixture
        # because macOS temporary roots can contain a /var symlink.
        self.root = Path(tempfile.mkdtemp(prefix="router-claude-model-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "claude"
        self.session = str(uuid.uuid4())
        self.path = self.home / "projects" / "synthetic-project" / (self.session + ".jsonl")
        self.path.parent.mkdir(parents=True)
        self.event = dict(hook_event_name="PreToolUse", tool_name="Agent", session_id=self.session,
                          tool_use_id="toolu_synthetic123", transcript_path=str(self.path))
        self.sleep = self.enterContext(mock.patch.object(reader.time, "sleep"))

    def record(self, model="claude-opus-4-6"):
        return dict(type="assistant", sessionId=self.session,
                    message=dict(model=model, content=[dict(type="tool_use", name="Agent",
                                                             id=self.event["tool_use_id"],
                                                             input={"prompt": "SYNTHETIC_PRIVATE_TEXT"})]))

    def write(self, records):
        self.path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        return self.path

    def resolve(self, event=None):
        return reader.resolve_tool_model(self.event if event is None else event, self.home)

    def observed(self, event=None):
        observation = {"discarded": "value"}
        result = reader.resolve_tool_model(self.event if event is None else event, self.home,
                                           observation=observation)
        return result, observation

    def test_exact_match_returns_only_model_and_fixed_source(self):
        self.write([self.record()]).chmod(0o664)
        self.assertEqual(self.resolve(), {"model": "claude-opus-4-6", "source": "transcript_tool_use"})
        self.sleep.assert_not_called()

    def test_observation_first_hit_preserves_legacy_return(self):
        contents = json.dumps(self.record()).encode() + b"\n"
        self.path.write_bytes(contents)
        result, observation = self.observed()
        self.assertEqual(result, {"model": "claude-opus-4-6", "source": "transcript_tool_use"})
        self.assertEqual(observation, {"read_attempts": 1, "bytes_read": len(contents),
                                       "duration_ms": mock.ANY, "outcome": "resolved",
                                       "api_input_tokens": 0, "api_output_tokens": 0,
                                       "cost_usd": 0})
        self.assertGreaterEqual(observation["duration_ms"], 0)

    def test_observation_retry_and_not_found_are_bounded(self):
        self.sleep.side_effect = lambda _: self.write([self.record()])
        result, observation = self.observed()
        self.assertEqual(result["model"], "claude-opus-4-6")
        self.assertEqual(observation["read_attempts"], 2)
        self.assertEqual(observation["bytes_read"],
                         len(json.dumps(self.record()).encode()) + 1)
        self.assertEqual(observation["outcome"], "resolved")

        self.path.unlink()
        self.sleep.side_effect = None
        result, observation = self.observed()
        self.assertEqual(result, {})
        self.assertEqual(observation["read_attempts"], 2)
        self.assertEqual(observation["bytes_read"], 0)
        self.assertEqual(observation["outcome"], "not_found")

    def test_observation_rejects_invalid_identity_and_read_errors(self):
        result, observation = self.observed({**self.event, "tool_name": "Task"})
        self.assertEqual(result, {})
        self.assertEqual(observation["read_attempts"], 0)
        self.assertEqual(observation["bytes_read"], 0)
        self.assertEqual(observation["outcome"], "rejected")

        self.write([self.record()])
        with mock.patch.object(reader.os, "read", side_effect=OSError("synthetic failure")):
            result, observation = self.observed()
        self.assertEqual(result, {})
        self.assertEqual(observation["read_attempts"], 1)
        self.assertEqual(observation["bytes_read"], 0)
        self.assertEqual(observation["outcome"], "rejected")

    def test_observation_counts_os_read_bytes_before_partial_line_discard(self):
        prefix = b"x" * 9
        self.path.write_bytes(prefix + b"\n" + b"x" * reader._TAIL_BYTES)
        result, observation = self.observed()
        self.assertEqual(result, {})
        self.assertEqual(observation["read_attempts"], 2)
        self.assertEqual(observation["bytes_read"], 2 * reader._TAIL_BYTES)
        self.assertEqual(observation["outcome"], "not_found")

    def test_never_borrows_other_session_id_tool_or_record_type(self):
        for variant in ("session", "id", "tool", "type", "block_type", "content"):
            with self.subTest(variant=variant):
                record = self.record()
                if variant == "session":
                    record["sessionId"] = str(uuid.uuid4())
                elif variant == "type":
                    record["type"] = "user"
                elif variant == "content":
                    record["message"]["content"] = {"type": "tool_use"}
                else:
                    key = {"id": "id", "tool": "name", "block_type": "type"}[variant]
                    record["message"]["content"][0][key] = "other"
                self.write([record])
                self.assertEqual(self.resolve(), {})

    def test_matching_record_wins_over_newer_unrelated_assistant(self):
        other = self.record("claude-sonnet-4-6")
        other["message"]["content"][0]["id"] = "other_id"
        self.write([self.record(), other])
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_same_model_duplicates_allowed_conflicts_fail_closed(self):
        self.write([self.record(), self.record()])
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        for models in (("claude-opus-4-6", "claude-sonnet-4-6"),
                       ("claude-sonnet-4-6", "claude-opus-4-6")):
            self.write([self.record(model) for model in models])
            self.assertEqual(self.resolve(), {})
        self.sleep.assert_not_called()

    def test_invalid_matching_model_blocks_valid_in_either_order(self):
        for invalid in (None, {}, [], 1, True, "", "inherit", "default", "auto", "unknown",
                        "x" * 201, "bad\nmodel", "model secret text", "☃"):
            with self.subTest(model=invalid):
                for records in ([self.record(), self.record(invalid)],
                                [self.record(invalid), self.record()]):
                    self.write(records)
                    self.assertEqual(self.resolve(), {})
        self.sleep.assert_not_called()

    def test_missing_matching_model_is_unknown(self):
        record = self.record()
        del record["message"]["model"]
        self.write([self.record(), record])
        self.assertEqual(self.resolve(), {})
        self.sleep.assert_not_called()

    def test_invalid_events_never_open_any_path(self):
        cases = [None, [], "event", {}, {**self.event, "agent_id": None},
                 {**self.event, "turn_id": None}]
        for key, values in {
            "session_id": [None, {}, "bad", "0" * 36],
            "tool_use_id": [None, [], "", "x" * 201, "../tool", "tool\n"],
            "hook_event_name": ["PostToolUse", "SessionStart", None],
            "tool_name": ["Task", "spawn_agent", None],
            "transcript_path": [None, [], "", "relative.jsonl", "/tmp/\x00bad", "x" * 4097],
        }.items():
            cases.extend({**self.event, key: value} for value in values)
        with mock.patch.object(reader.os, "open", side_effect=AssertionError("unexpected open")):
            for event in cases:
                with self.subTest(event=event):
                    self.assertEqual(reader.resolve_tool_model(event, self.home), {})
        self.sleep.assert_not_called()

    def test_outside_wrong_name_and_traversal_never_open(self):
        paths = [self.root / (self.session + ".jsonl"),
                 self.home / "projects-sibling" / "p" / (self.session + ".jsonl"),
                 self.path.with_name(str(uuid.uuid4()) + ".jsonl"),
                 self.path.parent / ".." / "synthetic-project" / self.path.name,
                 self.home / "projects" / self.path.name]
        with mock.patch.object(reader.os, "open", side_effect=AssertionError("unexpected open")):
            for path in paths:
                self.assertEqual(self.resolve({**self.event, "transcript_path": str(path)}), {})

    def test_only_exact_file_opened_without_directory_scans(self):
        self.write([self.record()])
        with mock.patch.object(reader.os, "open", wraps=os.open) as opened, \
                mock.patch.object(reader.os, "listdir", side_effect=AssertionError("scan")), \
                mock.patch.object(reader.os, "scandir", side_effect=AssertionError("scan")), \
                mock.patch.object(Path, "glob", side_effect=AssertionError("scan")):
            self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        expected = ["/"] + list(self.path.parts[1:])
        self.assertEqual([call.args[0] for call in opened.call_args_list], expected)
        for call in opened.call_args_list:
            self.assertTrue(call.args[1] & os.O_NOFOLLOW)

    def test_symlink_file_and_ancestor_rejected_without_reads(self):
        target = self.root / "synthetic-target"
        target.write_text(json.dumps(self.record()))
        self.path.symlink_to(target)
        with mock.patch.object(reader.os, "read", side_effect=AssertionError("read")):
            self.assertEqual(self.resolve(), {})
        self.path.unlink()
        actual = self.root / "synthetic-real-project"
        self.path.parent.rename(actual)
        self.path.parent.symlink_to(actual, target_is_directory=True)
        with mock.patch.object(reader.os, "read", side_effect=AssertionError("read")):
            self.assertEqual(self.resolve(), {})
        self.sleep.assert_not_called()

    def test_symlink_above_claude_home_is_rejected(self):
        self.write([self.record()])
        alias = self.root / "alias"
        alias.symlink_to(self.home, target_is_directory=True)
        event = {**self.event, "transcript_path": str(alias / self.path.relative_to(self.home))}
        with mock.patch.object(reader.os, "read", side_effect=AssertionError("read")):
            self.assertEqual(reader.resolve_tool_model(event, alias), {})

    def test_wrong_owner_directory_and_fifo_rejected_before_read(self):
        self.write([self.record()])
        with mock.patch.object(reader.os, "geteuid", return_value=os.geteuid() + 1), \
                mock.patch.object(reader.os, "read", side_effect=AssertionError("read")):
            self.assertEqual(self.resolve(), {})
        self.path.unlink()
        for create in (lambda: self.path.mkdir(), lambda: os.mkfifo(self.path)):
            create()
            with mock.patch.object(reader.os, "read", side_effect=AssertionError("read")):
                self.assertEqual(self.resolve(), {})
            self.path.rmdir() if self.path.is_dir() else self.path.unlink()
        self.sleep.assert_not_called()

    def test_one_retry_for_late_file(self):
        self.sleep.side_effect = lambda _: self.write([self.record()])
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        self.sleep.assert_called_once_with(0.1)

    def test_one_retry_for_late_matching_append(self):
        self.write([{"type": "assistant", "message": {"model": "wrong"}}])
        def append(_):
            with self.path.open("a") as stream:
                stream.write(json.dumps(self.record()) + "\n")
        self.sleep.side_effect = append
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        self.sleep.assert_called_once_with(0.1)

    def test_absent_file_stops_after_one_retry(self):
        with mock.patch.object(reader, "_read_tail", wraps=reader._read_tail) as read:
            self.assertEqual(self.resolve(), {})
        self.assertEqual(read.call_count, 2)
        self.sleep.assert_called_once_with(0.1)

    def test_malformed_json_and_structures_never_expose_text(self):
        self.path.write_bytes(b"{broken\n\xff\n" + b"[" * 2000 + b"\nnull\n[]\n"
                             + b'{"type":"assistant","message":null}\n')
        self.assertEqual(self.resolve(), {})
        with self.path.open("a") as stream:
            stream.write(json.dumps(self.record()) + "\n")
        self.assertEqual(self.resolve(), {"model": "claude-opus-4-6", "source": "transcript_tool_use"})

    def test_read_budget_and_old_match_never_triggers_history_read(self):
        self.write([self.record(), {"padding": "x" * (reader._TAIL_BYTES + 100)}])
        with mock.patch.object(reader.os, "read", wraps=os.read) as read:
            self.assertEqual(self.resolve(), {})
        counts = [call.args[1] for call in read.call_args_list]
        self.assertEqual(counts, [1024 * 1024, 1024 * 1024])
        self.assertLessEqual(sum(counts), 2 * 1024 * 1024)

    def test_tail_match_after_oversized_older_record(self):
        self.write([{"padding": "x" * (reader._TAIL_BYTES + 100)}, self.record()])
        self.assertEqual(self.resolve()["model"], "claude-opus-4-6")

    def test_partial_tail_first_line_not_parsed_as_forged_record(self):
        forged = json.dumps(self.record()).encode()
        suffix = forged + b"\n" + b" " * (reader._TAIL_BYTES - len(forged) - 1)
        self.path.write_bytes(b"not-a-json-prefix" + suffix)
        self.assertEqual(self.resolve(), {})

    def test_root_default_env_and_explicit_override(self):
        self.write([self.record()])
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)}):
            self.assertEqual(reader.resolve_tool_model(self.event)["model"], "claude-opus-4-6")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "elsewhere")}):
            self.assertEqual(self.resolve()["model"], "claude-opus-4-6")
        default_home = self.root / ".claude"
        self.home.rename(default_home)
        event = copy.deepcopy(self.event)
        event["transcript_path"] = str(default_home / self.path.relative_to(self.home))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}), \
                mock.patch.object(reader.Path, "home", return_value=self.root):
            self.assertEqual(reader.resolve_tool_model(event)["model"], "claude-opus-4-6")

    def test_read_os_error_fails_closed_without_retry(self):
        self.write([self.record()])
        with mock.patch.object(reader.os, "read", side_effect=OSError("synthetic failure")):
            self.assertEqual(self.resolve(), {})
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
