"""Claude lifecycle -> routing -> telemetry; only isolated state and fake Jev."""
import io
import json
import os
import sys
import uuid
from unittest import mock

from test_router import Sandbox, agent_input, router
import router_claude_state
import router_telemetry


class ClaudeStateIntegrationTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.home.chmod(0o700)
        self.session = str(uuid.uuid4())
        self.identity = {"session_id": self.session,
                         "transcript_path": str(self.root / (self.session + ".jsonl"))}

    def lifecycle(self, kind, **fields):
        result = self.run_router("claude-session", stdin=json.dumps(
            dict(self.identity, hook_event_name=kind, **fields)))
        self.assertEqual(result[:3], (0, "", ""))

    def event(self, **fields):
        return dict(self.identity, hook_event_name="PreToolUse", tool_name="Agent",
                    tool_input=agent_input(), effort={"level": "medium"}, **fields)

    def decision(self, event=None, mode="active", model="inherit", env=None, observe=False):
        cfg = router.normalize_config({"mode": mode, "claude": {"models": {"heavy": model},
                                                                "observe_transcript_model": observe}})
        event = event or self.event()
        record = router.base_record(event, "claude")
        record.update(mode=mode, tier="heavy")
        with mock.patch.dict(os.environ, env or self.env(), clear=True):
            return router._claude_decision(cfg, event, event["tool_input"], "heavy", "risky", record)

    def test_start_switch_resume_end_flow_preserves_routing(self):
        self.write_config()
        self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
        output, record = self.decision()
        self.assertIsNone(output)
        self.assertEqual(record["session_model"], "claude-opus-4-6")
        self.assertEqual(record["session_model_source"], "session_start")
        self.assertIn("model=claude-opus-4-6 (unchanged), effort=medium", router.decision_notice(record))
        self.lifecycle("PostModelSwitch", source="command", from_model="claude-opus-4-6",
                       to_model="claude-sonnet-4-6")
        _, record = self.decision()
        self.assertEqual(record["session_model"], "claude-sonnet-4-6")
        self.assertEqual(record["session_model_source"], "post_model_switch")
        self.lifecycle("SessionStart", source="resume")
        self.assertIsNone(self.decision()[1]["session_model"])
        self.lifecycle("SessionStart", source="resume", model="claude-opus-4-6")
        self.lifecycle("SessionEnd", reason="prompt_input_exit")
        self.assertIsNone(self.decision()[1]["session_model"])

    def test_no_config_does_not_create_checkpoint(self):
        self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
        self.assertFalse((self.home / ".local/state/subagent-model-router/claude-sessions").exists())

    def test_config_missing_or_broken_during_resume_clears_old_model(self):
        for broken in (False, True):
            with self.subTest(broken=broken):
                self.write_config()
                self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
                if broken:
                    self.config.write_text("invalid = [")
                else:
                    self.config.unlink()
                self.lifecycle("SessionStart", source="resume")
                self.write_config()
                self.assertIsNone(self.decision()[1]["session_model"])

    def test_event_model_wins_and_changed_model_custom_or_overrides_do_not_read_cache(self):
        with mock.patch.object(router_claude_state, "resolve_session") as resolve:
            _, record = self.decision(self.event(model="claude-sonnet-4-6"))
            self.assertEqual(record["session_model"], "claude-sonnet-4-6")
            self.decision(model="haiku")
            self.decision(dict(self.event(), tool_input=agent_input(subagent_type="custom")))
            for key in ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"):
                self.decision(env=self.env(**{key: "sonnet"}))
            resolve.assert_not_called()

    def test_nested_agent_and_foreign_session_stay_unknown(self):
        self.write_config()
        self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
        self.assertIsNone(self.decision(self.event(agent_id="child"))[1]["session_model"])
        self.assertIsNone(self.decision(dict(self.event(), session_id=str(uuid.uuid4())))[1]["session_model"])

    def test_shadow_uses_session_for_actual_model_but_keeps_recommendation(self):
        self.write_config()
        self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
        output, record = self.decision(mode="shadow", model="haiku")
        self.assertIsNone(output)
        self.assertEqual(record["model"], "haiku")
        self.assertEqual(record["session_model"], "claude-opus-4-6")

    def test_changed_model_notice_does_not_attribute_parent_effort(self):
        _, record = self.decision(model="haiku")
        notice = router.decision_notice(record)
        self.assertIn("model=haiku", notice)
        self.assertNotIn("effort=medium", notice)

    def test_transcript_lookup_requires_opt_in_and_never_overrides_lifecycle(self):
        import router_claude_model
        observation = {"model": "claude-sonnet-4-6", "source": "transcript_tool_use"}
        with mock.patch.object(router_claude_model, "resolve_tool_model", return_value=observation) as read:
            self.decision()
            read.assert_not_called()
            _, record = self.decision(observe=True)
            self.assertEqual(record["session_model_source"], "transcript_tool_use")
            self.assertEqual(record["session_model"], "claude-sonnet-4-6")
            read.reset_mock()
            self.write_config()
            self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
            _, record = self.decision(observe=True)
            self.assertEqual(record["session_model"], "claude-opus-4-6")
            read.assert_not_called()

    def test_startup_without_model_resolves_exact_current_agent_record(self):
        self.write_config()
        self.lifecycle("SessionStart", source="startup")
        transcript = self.home / ".claude/projects/synthetic" / (self.session + ".jsonl")
        transcript.parent.mkdir(parents=True, mode=0o700)
        transcript.write_text(json.dumps({"type": "assistant", "sessionId": self.session,
            "message": {"model": "claude-opus-4-6", "content": [
                {"type": "tool_use", "name": "Agent", "id": "toolu_current", "input": {"prompt": "synthetic"}}]}}) + "\n")
        event = dict(self.event(), transcript_path=str(transcript), tool_use_id="toolu_current")
        output, record = self.decision(event, observe=True)
        self.assertIsNone(output)
        self.assertEqual(record["session_model"], "claude-opus-4-6")
        self.assertEqual(record["session_model_source"], "transcript_tool_use")
        self.assertIn("model=claude-opus-4-6 (unchanged), effort=medium", router.decision_notice(record))
        self.assertNotIn("synthetic", json.dumps(record))

    def test_transcript_opt_in_must_be_boolean(self):
        with self.assertRaises(router.ConfigError):
            router.normalize_config({"claude": {"observe_transcript_model": "true"}})

    def test_hook_exports_lifecycle_model_source_and_observed_effort(self):
        self.write_config()
        self.lifecycle("SessionStart", source="startup", model="claude-opus-4-6")
        cfg = router.normalize_config({"telemetry": {
            "backend": "victoriametrics", "write_url": "http://127.0.0.1:8428/api/v1/import/prometheus",
            "query_url": "http://127.0.0.1:8428", "instance": "test"}})
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(self.event()).encode()))
        stdout = io.StringIO()
        try:
            with mock.patch.dict(os.environ, self.env(), clear=True), \
                    mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
                    mock.patch.object(sys, "stderr", io.StringIO()), \
                    mock.patch.object(router, "load_config", return_value=cfg), \
                    mock.patch.object(router, "read_key", return_value=("fake", None)), \
                    mock.patch.object(router, "ask_jev", return_value={"probs": {}, "jev_model": "fake",
                                                                       "request_id": "fake", "latency_ms": 1}), \
                    mock.patch.object(router, "choose_tier", return_value=("heavy", "risky")), \
                    mock.patch.object(router, "rounded_answers", return_value={}), \
                    mock.patch.object(router_telemetry, "enqueue", return_value=True) as enqueue:
                self.assertEqual(router.hook_main(), 0)
                sys.stderr.close()
            record = enqueue.call_args.args[1]
            self.assertEqual(record["actual_model"], "claude-opus-4-6")
            self.assertEqual(record["actual_effort"], "medium")
            self.assertEqual(record["model_source"], "session_start")
            points = router_telemetry._points(cfg["telemetry"], record, .01)
            call = next(p for p in points if p.startswith("smr_calls_total{"))
            self.assertIn('model="claude-opus-4-6"', call)
            self.assertIn('model_source="session_start"', call)
            self.assertIn('effort="medium"', call)
            self.assertIn("model=claude-opus-4-6 (unchanged)", json.loads(stdout.getvalue())["systemMessage"])
        finally:
            stdin.close()
