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
        out = t.format_terminal(t.local_data([{'ts':'2026-01-01T00:00:00Z','agent':'codex','model':'bad`\n|x','reason':'rule:x','latency_ms':10}]))
        self.assertIn("bad' ¦x", out); self.assertNotIn('```', out); self.assertNotIn('\x1b', out); self.assertIn('█', out)
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
    def test_gap(self):
        data=t.local_data([]); data.update({'status':'partial','series':{'request_rate':[{'points':[[0,1],[60,None],[120,3]]}]}})
        self.assertIn('·', t.format_terminal(data))
    def test_cohorts_latency(self):
        data=t.local_data([{'ts':'2026-01-01T00:00:00Z','agent':'claude','model':'m1','reason':'rule:a','latency_ms':10},{'ts':'2026-01-01T00:01:00Z','agent':'codex','model':'m2','reason':'error:x'}])
        self.assertEqual(data['summary']['by_agent'], {'claude':1,'codex':1}); self.assertEqual(data['summary']['by_model'], {'m1':1}); self.assertEqual(data['summary']['jev_p50_seconds'], .01); self.assertIsNone(data['summary']['hook_p50_seconds'])

if __name__ == '__main__': unittest.main()
