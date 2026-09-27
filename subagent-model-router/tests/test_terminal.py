import sys
import unittest
import datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import router_terminal as t

class TerminalTests(unittest.TestCase):
    def test_local_client_filter_and_html(self):
        from router_dashboard import html_document
        rows = [{'ts': '2026-01-01T00:00:00Z', 'agent': a, 'reason': 'explicit'} for a in ('codex', 'claude')]
        data = t.local_data(rows, agent='codex')
        self.assertEqual(data['summary']['calls'], 1)
        self.assertEqual(data['summary']['by_agent'], {'codex': 1})
        self.assertIn('Agent: codex', html_document(data))
        self.assertEqual(t.local_data(rows, user='missing')['status'], 'no_data')
    def test_local_window_requests_and_failures(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = {'ts': '2026-01-09T00:00:00Z'}
        rows = [dict(base, reason='explicit'), dict(base, reason='error:config'),
                dict(base, reason='rule:light', latency_ms=10, model='haiku', mode='shadow'),
                dict(base, reason='error:timeout', latency_ms=1000),
                dict(base, ts='2025-01-01T00:00:00Z', reason='rule:light'),
                dict(base, ts='2027-01-01T00:00:00Z', reason='rule:light')]
        data = t.local_data(rows, days=7, now=now)
        self.assertEqual(data['summary']['calls'], 4)
        self.assertEqual(data['summary']['jev_requests'], 2)
        self.assertEqual(data['summary']['error_share'], .5)
        self.assertEqual(data['summary']['applied'], 0)
        self.assertEqual(data['summary']['jev_p99_seconds'], 1)
        self.assertEqual(data['end'], now.timestamp())

    def test_local_selection_and_submitted_pairs_do_not_use_parent(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        selected = dict(ts='2026-01-09T00:00:00Z', agent='codex', reason='choice',
                        model='gpt-6-astra', effort='high', actual_model=None, actual_effort=None,
                        session_model='gpt-5.6-luna', session_effort='low', mode='shadow', applied=False,
                        jev_attempted=True, jev_outcome='success')
        data = t.local_data([selected], now=now)
        self.assertEqual(data['summary']['by_recommended_model'], {'gpt-6-astra': 1})
        self.assertEqual(data['summary']['by_model'], {'unknown': 1})
        self.assertNotIn('gpt-5.6-luna', t.format_terminal(data))
        from router_dashboard import html_document
        self.assertIn('gpt-6-astra', html_document(data))

    def test_local_no_effort_uses_direct_launch_evidence(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        active = dict(ts='2026-01-09T00:00:00Z', agent='claude', reason='choice', model='fable', effort=None,
                      actual_model='fable', actual_effort=None, mode='active', applied=True,
                      jev_attempted=True, jev_outcome='success', selected_effort_supported=False)
        data = t.local_data([active], now=now)
        self.assertEqual(data['summary']['by_recommended_effort'], {'not_supported': 1})
        self.assertEqual(data['summary']['by_effort'], {'not_supported': 1})
        shadow = dict(active, actual_model=None, mode='shadow', applied=False)
        data = t.local_data([shadow], now=now)
        self.assertEqual(data['summary']['by_effort'], {'not_set': 1})
        explicit = dict(active, reason='explicit', jev_attempted=False, jev_outcome=None)
        data = t.local_data([explicit], now=now)
        self.assertEqual(data['summary']['by_effort'], {'not_set': 1})

    def test_local_capability_and_dynamic_model_evidence_match_export(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        active = dict(ts='2026-01-09T00:00:00Z', reason='choice', model='future/vendor@2027', effort=None,
                      actual_model='future/vendor@2027', actual_effort=None, mode='active', applied=True,
                      jev_attempted=True, jev_outcome='success')
        data = t.local_data([active], now=now)
        self.assertEqual(data['summary']['by_recommended_model'], {'future/vendor@2027': 1})
        self.assertEqual(data['summary']['by_model'], {'future/vendor@2027': 1})
        self.assertEqual(data['summary']['by_recommended_effort'], {'unknown': 1})
        self.assertEqual(data['summary']['by_effort'], {'not_set': 1})
        unsupported = dict(active, selected_effort_supported=False)
        data = t.local_data([unsupported], now=now)
        self.assertEqual(data['summary']['by_recommended_effort'], {'not_supported': 1})
        self.assertEqual(data['summary']['by_effort'], {'not_supported': 1})
        explicit = dict(active, reason='explicit', jev_attempted=False, jev_outcome=None)
        data = t.local_data([explicit], now=now)
        self.assertEqual(data['summary']['by_recommended_model'], {})
        self.assertEqual(data['summary']['by_model'], {'unknown': 1})

    def test_local_new_records_use_explicit_jev_attempt_evidence(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        preflight = dict(ts='2026-01-09T00:00:00Z', reason='error:no_catalog', latency_ms=1,
                         state_sha256='digest', jev_attempted=False, jev_outcome=None)
        launch_failure = dict(ts='2026-01-09T00:00:01Z', reason='error:claude_effort_definition', latency_ms=1,
                              jev_attempted=True, jev_outcome='success')
        data = t.local_data([preflight, launch_failure], now=now)
        self.assertEqual(data['summary']['jev_requests'], 1)
        self.assertEqual(data['summary']['jev_errors'], 0)

    def test_unknown_empty_values_and_control_characters(self):
        data = t.local_data([])
        self.assertIsNone(data['summary']['error_share'])
        self.assertIsNone(data['summary']['calls'])
        self.assertNotIn('\u202e', t._clean('\u202e[evil](url)<script>'))
        self.assertNotIn('[', t._clean('[evil](url)'))

    def test_missing_timestamps_and_series_labels(self):
        data = t.local_data([])
        data.update(step=60, series={'request_rate': [{'labels': {'outcome': 'success'},
                    'points': [[0, 1], [180, 2]]}]})
        output = t.format_terminal(data)
        self.assertIn('success', output)
        self.assertIn('·', output)
        self.assertIn('·', t._spark([[i, None if i == 12 else 1] for i in range(64)]))
    def test_escape(self):
        out = t.format_terminal(t.local_data([{'ts':'2026-01-01T00:00:00Z','agent':'codex','model':'x','actual_model':'bad`\n|x','reason':'choice','latency_ms':10,'jev_attempted':True,'jev_outcome':'success'}]))
        self.assertNotIn('bad', out); self.assertNotIn('```', out); self.assertNotIn('\x1b', out); self.assertIn('█', out)
    def test_empty(self):
        out = t.format_terminal(t.local_data([])); self.assertIn('no_data', out); self.assertIn('нет данных', out)
    def test_reported_cost_missing_zero_and_subcent_precision(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-09T00:00:00Z', reason='rule:light', latency_ms=1)
        old = t.local_data([base], days=7, now=now)
        self.assertIsNone(old['summary']['jev_cost_usd'])
        self.assertEqual(old['summary']['jev_unpriced_requests'], 1)
        data = t.local_data([base, dict(base, usage={'cost': 0}), dict(base, usage={'cost': .000004}),
                             dict(base, usage={'cost': True}), dict(base, usage={'cost': -1})], days=7, now=now)
        self.assertEqual(data['summary']['jev_cost_usd'], .000004)
        self.assertEqual(data['summary']['jev_cost_coverage'], .4)
        self.assertEqual(data['summary']['jev_unpriced_requests'], 3)
        self.assertIn('$0.000004', t.format_terminal(data))
        self.assertIsNone(data['summary']['jev_cost_rate_current'])

    def test_local_token_coverage_and_lookup_observations(self):
        from router_dashboard import html_document, format_summary
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-09T00:00:00Z', reason='rule:light', latency_ms=1,
                    project='repo', user='dev', agent='claude')
        lookup = dict(read_attempts=2, bytes_read=1024, duration_ms=15, outcome='resolved',
                      api_input_tokens=0, api_output_tokens=0, cost_usd=0)
        rows = [base, dict(base, usage={'input_tokens': 0, 'output_tokens': 2}, claude_model_lookup=lookup),
                dict(base, usage={'input_tokens': 12, 'output_tokens': True}),
                dict(base, usage={'input_tokens': -1, 'output_tokens': 1.5}),
                dict(base, usage={'input_tokens': '3', 'output_tokens': float('inf')}),
                dict(base, agent='codex', usage={'input_tokens': 999}, claude_model_lookup=lookup),
                dict(base, project='other', claude_model_lookup=lookup),
                dict(base, user='other', claude_model_lookup=lookup)]
        data = t.local_data(rows, days=7, now=now, project='repo', user='dev', agent='claude')
        s = data['summary']
        self.assertEqual(s['jev_input_tokens'], 12)
        self.assertEqual(s['jev_input_token_coverage'], .4)
        self.assertEqual(s['jev_output_tokens'], 2)
        self.assertEqual(s['jev_output_token_coverage'], .2)
        self.assertEqual(s['claude_model_lookup_requests'], 1)
        self.assertEqual(s['claude_model_lookup_read_attempts'], 2)
        self.assertEqual(s['claude_model_lookup_bytes_read'], 1024)
        self.assertEqual(s['claude_model_lookup_duration_seconds'], .015)
        self.assertEqual(s['claude_model_lookup_cost_usd'], 0)
        self.assertEqual(s['claude_model_lookup_api_input_tokens'], 0)
        self.assertNotIn('Чтение модели Claude', t.format_terminal(data))
        self.assertIn('Jev input token coverage</td><td>40.0%', html_document(data))
        self.assertNotIn('Claude model lookup', format_summary(data))
        zero = t.local_data([dict(base, usage={'input_tokens': 0})], now=now)['summary']
        self.assertEqual(zero['jev_input_tokens'], 0)
        self.assertEqual(zero['jev_input_token_coverage'], 1)
        self.assertIsNone(zero['jev_output_tokens'])
        self.assertIsNone(zero['claude_model_lookup_cost_usd'])

    def test_invalid_lookup_and_missing_history_are_not_free(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-09T00:00:00Z', reason='explicit')
        lookup = dict(read_attempts=0, bytes_read=0, duration_ms=0, outcome='rejected',
                      api_input_tokens=0, api_output_tokens=0, cost_usd=0)
        invalid = [None, {}, dict(lookup, read_attempts=True), dict(lookup, read_attempts=3),
                   dict(lookup, bytes_read=2097153), dict(lookup, duration_ms=float('nan')),
                   dict(lookup, duration_ms=-1), dict(lookup, api_input_tokens=1), dict(lookup, bytes_read=10**1000),
                   dict(lookup, cost_usd=True), dict(lookup, outcome='invalid')]
        data = t.local_data([dict(base, claude_model_lookup=v) for v in invalid], now=now)
        for key in ('requests', 'read_attempts', 'bytes_read', 'duration_seconds', 'api_input_tokens', 'cost_usd'):
            self.assertIsNone(data['summary']['claude_model_lookup_' + key])
        observed = t.local_data([dict(base, claude_model_lookup=lookup)], now=now)
        self.assertEqual(observed['summary']['claude_model_lookup_requests'], 1)
        self.assertEqual(observed['summary']['claude_model_lookup_cost_usd'], 0)
        self.assertEqual(observed['summary']['jev_requests'], 0)

    def test_local_hook_versions_preserve_history_and_show_project(self):
        from router_dashboard import html_document, format_summary
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-08T00:00:00Z', reason='explicit', host='host', user='dev',
                    agent='claude', project='one', plugin_version='9.0')
        rows = [base, dict(base, ts='2026-01-09T00:00:00Z', project='two', plugin_version='1.0'),
                dict(base, host='', plugin_version='invalid'), dict(base, plugin_version=None),
                dict(base, host='other', user='other'), dict(base, agent='codex'),
                dict(base, ts='2027-01-01T00:00:00Z', plugin_version='future')]
        data = t.local_data(rows, days=7, now=now, user='dev', agent='claude')
        versions = data['summary']['hook_versions']
        self.assertEqual([(v['project'], v['plugin_version']) for v in versions], [('two', '1.0'), ('one', '9.0')])
        self.assertTrue(versions[0]['latest_observed'])
        self.assertFalse(versions[1]['latest_observed'])
        self.assertEqual(versions[0]['age_seconds'], 86400)
        self.assertEqual(data['summary']['hook_version_metadata_gaps'], 2)
        self.assertEqual(data['summary']['hook_version_mixed_reporters'], 1)
        self.assertEqual(data['summary']['calls'], 4)
        out = t.format_terminal(data)
        self.assertIn('историческая', out)
        self.assertIn('| Instance / host / user / клиент | Проект | Плагин |', out)
        self.assertIn('| local journal / host / dev / claude | two | 1.0 |', out)
        self.assertIn('фильтр project, если он задан', out)
        self.assertNotIn('независимо от project', out)
        self.assertIn('<td>claude</td><td>one</td><td>9.0</td>', html_document(data))
        self.assertIn('project=two; plugin=1.0', format_summary(data))
        self.assertNotIn('independent of project', html_document(data))
        # The project filter now applies to hook-version rows as well.
        one = t.local_data(rows, days=7, now=now, project='one', user='dev', agent='claude')['summary']
        self.assertEqual([(v['project'], v['plugin_version']) for v in one['hook_versions']], [('one', '9.0')])
        self.assertEqual(one['calls'], 3)
        old = t.local_data([dict(ts=base['ts'], reason='explicit')], now=now)
        self.assertEqual(old['summary']['hook_versions'], [])
        self.assertEqual(old['summary']['hook_version_metadata_gaps'], 1)
        self.assertIn('нет наблюдений версий', t.format_terminal(old))

    def test_local_project_resolution_from_cwd(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-09T00:00:00Z', reason='explicit', host='host', user='dev', agent='codex', plugin_version='1.0')
        rows = [dict(base, cwd='/nonexistent-smr-test/work/alpha'), dict(base, cwd='relative/beta'),
                dict(base), dict(base, project='recorded', cwd='/nonexistent-smr-test/work/alpha')]
        data = t.local_data(rows, now=now)
        self.assertEqual(data['summary']['by_project'], {'alpha': 1, 'unknown': 2, 'recorded': 1})
        self.assertEqual(sorted(v['project'] for v in data['summary']['hook_versions']), ['alpha', 'recorded', 'unknown'])
        self.assertEqual(t.local_data(rows, now=now, project='alpha')['summary']['calls'], 1)

    def test_local_models_by_project(self):
        from router_dashboard import html_document, format_summary
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        ok = dict(ts='2026-01-09T00:00:00Z', agent='codex', jev_attempted=True, jev_outcome='success')
        rows = [dict(ok, cwd='/nonexistent-smr-test/alpha', reason='choice', model='gpt-6-astra', actual_model='gpt-6-astra', applied=True, mode='active'),
                dict(ok, cwd='/nonexistent-smr-test/alpha', reason='choice', model='gpt-6-astra', actual_model=None, applied=False, mode='shadow'),
                dict(ok, cwd='/nonexistent-smr-test/alpha', reason='policy', model='gpt-6-nova', actual_model='gpt-6-nova', applied=True, mode='active',
                     choice_model='gpt-6-astra', choice_effort='low'),
                dict(ok, cwd='/nonexistent-smr-test/beta', reason='explicit', jev_attempted=False, jev_outcome=None,
                     actual_model='<b>x</b>', model_source='specified'),
                dict(ok, cwd='/nonexistent-smr-test/beta', reason='explicit', jev_attempted=False, jev_outcome=None,
                     actual_model='gpt-6-luna', model_source='specified'),
                dict(ok, cwd='/nonexistent-smr-test/beta', reason='explicit', jev_attempted=False, jev_outcome=None,
                     actual_model='gpt-6-luna', model_source='unknown'),
                dict(ok, cwd='/nonexistent-smr-test/beta', reason='choice', model='gpt-6-astra', actual_model='gpt-6-luna', applied=True)]
        s = t.local_data(rows, now=now)['summary']
        self.assertEqual(s['models_by_project'], [
            {'project': 'alpha', 'model': 'gpt-6-astra', 'calls': 1}, {'project': 'alpha', 'model': 'gpt-6-nova', 'calls': 1},
            {'project': 'beta', 'model': 'gpt-6-luna', 'calls': 1}])
        self.assertEqual(s['recommended_by_project'], [
            {'project': 'alpha', 'model': 'gpt-6-astra', 'calls': 3}, {'project': 'beta', 'model': 'gpt-6-astra', 'calls': 1}])
        data = t.local_data(rows, now=now)
        out = t.format_terminal(data)
        self.assertIn('**Модели по проектам**', out)
        self.assertIn('| alpha | gpt-6-astra | 1 | 3 |', out)
        self.assertIn('| alpha | gpt-6-nova | 1 | — |', out)
        self.assertIn('| beta | gpt-6-astra | — | 1 |', out)
        self.assertIn('<td>alpha</td><td>gpt-6-nova</td><td>1</td><td>-</td>', html_document(data))
        self.assertIn('beta · gpt-6-luna: 1 / -', format_summary(data))
        empty = t.local_data([], now=now)
        self.assertEqual(empty['summary']['models_by_project'], [])
        self.assertIn('| нет данных | нет данных | нет данных | нет данных |', t.format_terminal(empty))

    def test_local_policy_summary_unknown_vs_zero(self):
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        ok = dict(ts='2026-01-09T00:00:00Z', agent='codex', reason='choice', jev_attempted=True, jev_outcome='success')
        success = dict(policy='factors_v1', mode='shadow', outcome='success', level=3, model='gpt-6-astra', effort='high',
                       agreement='policy_higher', output_rate=10.0, adjustments=['impact_floor', 'confidence_raise:reasoning', 'bogus'])
        rows = [dict(ok, policy=success, choice_output_rate=2.0, selected_output_rate=2.0),
                dict(ok, policy=dict(success, level=True, agreement='nonsense', model='<script>', output_rate=None, adjustments=None),
                     choice_output_rate=4.0, selected_output_rate='5'),
                dict(ok, policy=dict(policy='factors_v1', outcome='error:range', agreement=None, level=2, output_rate=-1)),
                dict(ok, policy=dict(success, outcome='weird')),
                dict(ok, jev_attempted=False, jev_outcome=None, policy=success)]
        policy = t.local_data(rows, now=now)['summary']['policy']
        self.assertEqual(policy['decisions'], 4)
        self.assertEqual(policy['by_outcome'], {'success': 2, 'range': 1, 'unknown': 1})
        self.assertEqual(policy['outcome_errors'], 2)
        self.assertEqual(policy['by_agreement'], {'policy_higher': 2, 'unknown': 2})
        self.assertEqual(policy['by_level'], {'3': 1, 'none': 3})
        self.assertEqual(policy['by_model'], {'gpt-6-astra': 1, 'unknown': 1, 'none': 2})
        self.assertEqual(policy['adjustments'], {'impact_floor': 1, 'confidence_raise_reasoning': 1})
        self.assertEqual(policy['adjustments_total'], 2)
        # policy.output_rate is read from every row, including the non-attempted one.
        self.assertEqual(policy['priced_calls'], {'choice': 2, 'policy': 3, 'selected': 1})
        self.assertEqual(policy['average_output_usd_per_mtok'], {'choice': 3.0, 'policy': 10.0, 'selected': 2.0})
        out = t.format_terminal(t.local_data(rows, now=now))
        self.assertIn('**Факторная политика**', out)
        self.assertIn('Решений за окно: 4 · ошибки исхода: 2 (50.0%)', out)
        self.assertIn('Уровни: none 3 · 3 (сильный) 1.', out)
        self.assertIn('выбор Jev $3.000/Mtok (2 выз.)', out)
        self.assertNotIn('<script>', out)
        # Successes without adjustments are an observed zero; no policy records stay unknown.
        zero = t.local_data([dict(ok, policy=dict(success, adjustments=[]))], now=now)['summary']['policy']
        self.assertEqual(zero['adjustments_total'], 0)
        self.assertEqual(zero['outcome_errors'], 0)
        none = t.local_data([dict(ok)], now=now)['summary']['policy']
        for key in ('decisions', 'outcome_errors', 'outcome_error_share', 'adjustments_total'):
            self.assertIsNone(none[key], key)
        self.assertEqual(none['by_agreement'], {})
        self.assertEqual(none['average_output_usd_per_mtok'], {'choice': None, 'policy': None, 'selected': None})
        out = t.format_terminal(t.local_data([dict(ok)], now=now))
        self.assertIn('Решений за окно: нет данных · ошибки исхода: нет данных', out)
        self.assertIn('Согласие с выбором Jev: не наблюдалось.', out)
        self.assertIn('Корректировки: нет данных.', out)
        self.assertIn('выбор Jev нет данных', out)

    def test_terminal_renders_unavailable_vm_sections(self):
        data = t.local_data([])
        data['summary'].update(models_by_project=None, recommended_by_project=None,
                               policy={'decisions': None, 'by_agreement': None})
        out = t.format_terminal(data)
        self.assertIn('Согласие с выбором Jev: нет данных.', out)
        self.assertIn('| нет данных | нет данных | нет данных | нет данных |', out)

    def test_local_executing_client_version_is_distinct_from_plugin_and_model(self):
        from router_dashboard import format_summary, html_document
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
        base = dict(ts='2026-01-08T00:00:00Z', reason='explicit', host='host', user='dev',
                    agent='claude', plugin_version='0.4.8', model='claude-opus-4-6')
        rows = [base, dict(base, ts='2026-01-08T01:00:00Z', agent_version='2.1.20'),
                dict(base, ts='2026-01-09T00:00:00Z', agent_version='2.1.21'),
                dict(base, ts='2026-01-07T00:00:00Z', agent_version='invalid/private'),
                dict(base, ts='2026-01-07T00:00:00Z', agent_version='02.1.21')]
        data = t.local_data(rows, now=now)
        versions = data['summary']['hook_versions']
        self.assertEqual([v['agent_version'] for v in versions], ['2.1.21', '2.1.20', 'unknown'])
        self.assertTrue(versions[0]['latest_observed'])
        self.assertFalse(versions[1]['latest_observed'])
        self.assertEqual(data['summary']['hook_version_mixed_reporters'], 1)
        self.assertIn('| 0.4.8 | 2.1.21 |', t.format_terminal(data))
        self.assertIn('plugin=0.4.8; client=unknown', format_summary(data))
        self.assertIn('<th>Plugin version</th><th>Client version</th>', html_document(data))
        self.assertNotIn('invalid/private', html_document(data))
    def test_gap(self):
        data=t.local_data([]); data.update({'status':'partial','series':{'request_rate':[{'points':[[0,1],[60,None],[120,3]]}]}})
        self.assertIn('·', t.format_terminal(data))
    def test_cohorts_latency(self):
        data=t.local_data([{'ts':'2026-01-01T00:00:00Z','agent':'claude','model':'m1','reason':'rule:a','latency_ms':10},{'ts':'2026-01-01T00:01:00Z','agent':'codex','model':'m2','reason':'error:x'}])
        self.assertEqual(data['summary']['by_agent'], {'claude':1,'codex':1}); self.assertEqual(data['summary']['by_model'], {}); self.assertEqual(data['summary']['jev_p50_seconds'], .01); self.assertIsNone(data['summary']['hook_p50_seconds'])

if __name__ == '__main__': unittest.main()
