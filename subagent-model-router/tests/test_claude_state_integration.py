"""Claude direct selection uses only task and bundled definitions, never parent state."""
import io
import json
import os
import sys
from unittest import mock
from test_router import Sandbox, agent_input, router
import router_claude_state
import router_claude_model
import router_client_version
import router_telemetry


class ClaudeStateIntegrationTests(Sandbox):
    def event(self, **fields):
        return dict(hook_event_name='PreToolUse', tool_name='Agent', tool_input=agent_input(),
                    model='parent-never-selected', effort={'level': 'ultra'}, transcript_path='/must/not/open', **fields)

    def test_parent_and_transcript_readers_never_called_active_or_shadow(self):
        self.serve()
        for mode in ('active', 'shadow'):
            self.write_config(mode=mode)
            with mock.patch.dict(os.environ, self.env(), clear=True), \
                    mock.patch.object(router_claude_state, 'resolve_session', side_effect=AssertionError('parent read')), \
                    mock.patch.object(router_claude_model, 'resolve_tool_model', side_effect=AssertionError('transcript read')):
                output, record = router.handle_event(self.event(), 'claude')
            self.assertEqual(record['reason'], 'choice')
            self.assertEqual(record['model'], 'haiku')
            self.assertIsNone(record['effort'])
            self.assertNotIn('session_model', record)
            self.assertNotIn('session_effort', record)

    def test_sonnet_effort_uses_definition_never_unsupported_agent_argument(self):
        self.serve()
        self.write_config(claude={'allowed_models': ['sonnet'], 'efforts': ['high']})
        args = agent_input(extra={'keep': True}, run_in_background=True)
        output = json.loads(self.hook(args)[1])['hookSpecificOutput']['updatedInput']
        self.assertEqual(output, dict(args, model='sonnet', subagent_type='subagent-model-router:effort-high'))
        self.assertNotIn('effort', output)
        self.assertEqual(self.last_row()['effort'], 'high')

    def test_custom_types_cannot_be_routed_even_if_legacy_config_allows(self):
        self.serve()
        self.write_config(claude={'route_types': ['custom']})
        self.assertEqual(self.hook(agent_input(subagent_type='custom'))[:3], (0, '', ''))
        self.assertEqual(self.last_row()['reason'], 'type')
        self.assertEqual(self.fake.requests, [])

    def test_environment_overrides_skip_without_request(self):
        self.serve()
        self.write_config()
        for key in ('CLAUDE_CODE_SUBAGENT_MODEL_FORCE', 'CLAUDE_CODE_EFFORT_LEVEL',
                    'CLAUDE_CODE_COORDINATOR_FORCE_WORKER_INHERIT_MODEL'):
            self.assertEqual(self.hook(env=self.env(**{key: 'high'}))[:3], (0, '', ''))
            self.assertEqual(self.last_row()['reason'], 'override')
        self.assertEqual(self.fake.requests, [])

    def test_lifecycle_initializes_versions_but_never_model_state(self):
        self.write_config()
        for kind in ('SessionStart', 'PostModelSwitch', 'SessionEnd'):
            event = {'hook_event_name': kind, 'model': 'parent-never-selected'}
            stdin = io.TextIOWrapper(io.BytesIO(json.dumps(event).encode()))
            with mock.patch.dict(os.environ, self.env(), clear=True), mock.patch.object(sys, 'stdin', stdin), \
                    mock.patch.object(router_claude_state, 'update_session', side_effect=AssertionError('model state')), \
                    mock.patch.object(router_claude_state, 'invalidate_session', side_effect=AssertionError('model state')), \
                    mock.patch.object(router_client_version, 'initialize_client_version') as initialize:
                self.assertEqual(router.session_main(), 0)
                self.assertEqual(initialize.call_count, 2 if kind == 'SessionStart' else 0)
            stdin.close()

    def test_telemetry_contains_only_submitted_model_and_definition_effort(self):
        self.serve()
        self.write_config(claude={'allowed_models': ['opus'], 'efforts': ['max']}, telemetry={
            'backend': 'victoriametrics', 'write_url': 'http://127.0.0.1:8428/api/v1/import/prometheus',
            'query_url': 'http://127.0.0.1:8428', 'instance': 'test'})
        for mode in ('active', 'shadow'):
            with mock.patch.dict(os.environ, self.env(), clear=True):
                cfg = router.load_config()
            cfg['mode'] = mode
            stdin, stdout = io.TextIOWrapper(io.BytesIO(json.dumps(self.event()).encode())), io.StringIO()
            with mock.patch.dict(os.environ, self.env(), clear=True), mock.patch.object(sys, 'stdin', stdin), \
                    mock.patch.object(sys, 'stdout', stdout), mock.patch.object(sys, 'stderr', io.StringIO()), \
                    mock.patch.object(router, 'load_config', return_value=cfg), \
                    mock.patch.object(router_telemetry, 'enqueue', return_value=True) as enqueue:
                self.assertEqual(router.hook_main(), 0)
                sys.stderr.close()
            row = enqueue.call_args.args[1]
            if mode == 'active':
                self.assertEqual((row['actual_model'], row['actual_effort']), ('opus', 'max'))
                self.assertEqual(row['effort_source'], 'agent_definition')
                self.assertEqual(row['model_source'], 'updated_input')
            else:
                self.assertIsNone(row['actual_model'])
                self.assertIsNone(row['actual_effort'])
            stdin.close()
