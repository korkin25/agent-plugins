"""Inherited runtime effort is pinned only with exact-turn and catalog evidence."""
import sys
from unittest import mock
from test_router import Sandbox, router, v2_args

sys.path.insert(0, str(router.PLUGIN_ROOT) + '/lib')
import router_runtime


class RuntimeIntegrationTests(Sandbox):
    def decide(self, cfg=None, args=None, catalog=None):
        cfg = cfg or router.normalize_config({})
        args = args or v2_args()
        event = self.codex_event(args, session_model='gpt-6-astra')
        record = router.base_record(event, 'codex')
        record.update(mode=cfg['mode'], tier='heavy')
        with mock.patch.object(router, 'codex_catalog', return_value=(catalog or {'gpt-6-astra': ['high']}, None)):
            return router._codex_decision(cfg, event, args, 'heavy', 'risky', record)

    def test_exact_turn_effort_becomes_explicit_spawn_argument(self):
        with mock.patch.object(router_runtime, 'resolve_codex_turn', return_value={
                'model': 'gpt-6-astra', 'effort': 'high', 'source': 'turn_context'}):
            output, record = self.decide()
        self.assertEqual(output['hookSpecificOutput']['updatedInput']['reasoning_effort'], 'high')
        self.assertNotIn('model', output['hookSpecificOutput']['updatedInput'])
        self.assertEqual(record['applied_effort_source'], 'turn_context')
        self.assertIn('effort=high', router.decision_notice(record))

    def test_shadow_changed_model_and_custom_role_do_not_read_parent(self):
        configs = [router.normalize_config({'mode': 'shadow'}),
                   router.normalize_config({'codex': {'models': {'heavy': 'gpt-5.6-terra'}}}),
                   router.normalize_config({'codex': {'effort': {'heavy': 'low'}}})]
        with mock.patch.object(router_runtime, 'resolve_codex_turn') as read:
            for cfg in configs:
                self.decide(cfg)
            self.decide(args=v2_args(agent_type='custom'))
            read.assert_not_called()

    def test_absent_or_unsupported_catalog_never_claims_effort(self):
        with mock.patch.object(router_runtime, 'resolve_codex_turn', return_value={
                'model': 'gpt-6-astra', 'effort': 'ultra', 'source': 'turn_context'}):
            output, record = self.decide(catalog={'gpt-6-astra': ['high']})
        self.assertIsNone(output)
        self.assertNotIn('applied_effort_source', record)
        self.assertIn('effort=unknown', router.decision_notice(record))

    def test_explicit_skip_never_reads_runtime(self):
        event = self.codex_event(v2_args(reasoning_effort='low'))
        with mock.patch.object(router_runtime, 'resolve_codex_turn') as read:
            output, record = router.handle_event(event, 'codex')
            read.assert_not_called()
        self.assertIsNone(output)
        self.assertEqual(record['reason'], 'explicit')
