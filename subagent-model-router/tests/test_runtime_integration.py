"""Routing never observes parent model, effort, or transcript state."""
from unittest import mock
from test_router import Sandbox, router, v2_args
import router_runtime


class RuntimeIntegrationTests(Sandbox):
    def test_selected_pair_is_independent_of_parent_evidence(self):
        self.serve()
        self.write_config()
        event = self.codex_event(v2_args(), session_model='never-selected-parent')
        event.update(reasoning_effort='invented-parent-effort', transcript_path='/must/not/open')
        with mock.patch.dict('os.environ', self.env(), clear=True), \
                mock.patch.object(router_runtime, 'resolve_codex_turn', side_effect=AssertionError('parent read')), \
                mock.patch.object(router, 'parent_codex', return_value=None):
            output, record = router.handle_event(event, 'codex')
        updated = output['hookSpecificOutput']['updatedInput']
        self.assertEqual(updated['model'], 'gpt-5.5')
        self.assertEqual(updated['reasoning_effort'], 'high')
        self.assertNotIn('session_model', record)
        self.assertNotIn('session_effort', record)

    def test_skips_and_shadow_do_not_read_runtime(self):
        self.serve()
        self.write_config(mode='shadow')
        with mock.patch.dict('os.environ', self.env(), clear=True), \
                mock.patch.object(router_runtime, 'resolve_codex_turn', side_effect=AssertionError('parent read')), \
                mock.patch.object(router, 'parent_codex', return_value=None):
            for args in (v2_args(reasoning_effort='low'), v2_args(fork_turns='all'),
                         v2_args(agent_type='custom'), v2_args()):
                output, record = router.handle_event(self.codex_event(args), 'codex')
                self.assertNotIn('hookSpecificOutput', output or {})
                self.assertNotIn('session_effort', record)
