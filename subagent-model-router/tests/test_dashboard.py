"""Dashboard contracts, query failures and offline report safety."""
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.parse

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "lib"))
import router_dashboard as dashboard


def answer(rows, ranged=False):
    result = [{"metric": labels, "values" if ranged else "value": values}
              for labels, values in rows]
    return json.dumps({"status": "success", "data": {
        "resultType": "matrix" if ranged else "vector", "result": result}}).encode()


class DashboardTests(unittest.TestCase):
    def test_instant_category_panels_reduce_each_series_without_table_transform(self):
        doc = json.loads((PLUGIN / "grafana" / "subagent-model-router.json").read_text())
        for panel in (p for p in doc['panels'] if p['id'] in (10, 11, 12)):
            with self.subTest(panel=panel['title']):
                label = {10: 'model', 11: 'tier', 12: 'reason'}[panel['id']]
                self.assertEqual(panel['type'], 'bargauge')
                self.assertFalse(panel.get('transformations'))
                self.assertEqual(panel['options']['reduceOptions'],
                                 {'calcs': ['lastNotNull'], 'fields': '', 'values': False})
                expected_name = '${__field.labels.' + label + '}'
                if label == 'model':
                    expected_name += ' / ${__field.labels.effort}'
                    self.assertIn('sum by(model,effort)', panel['targets'][0]['expr'])
                    self.assertEqual(panel['targets'][0]['expr'].count('effort_source=~".+"'), 2)
                    legacy = next(p for p in doc['panels'] if p['id'] == 36)
                    self.assertIn('effort_source=""', legacy['targets'][0]['expr'])
                self.assertEqual(panel['fieldConfig']['defaults']['displayName'], expected_name)
                self.assertTrue(panel['targets'][0]['instant'])
                self.assertFalse(panel['targets'][0]['range'])
                if label != 'reason':
                    self.assertEqual(panel['fieldConfig']['defaults']['unit'], 'percentunit')
                    self.assertEqual(panel['fieldConfig']['defaults']['max'], 1)
    def test_health_only_is_no_data_for_selected_client(self):
        def respond(config, url, body=None):
            if 'smr_telemetry_' in urllib.parse.unquote(url):
                return answer([({}, [1700000000, '0'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            data = dashboard.query_stats(self.cfg, agent='codex')
        self.assertEqual(data['status'], 'no_data')
        self.assertIsNone(data['summary']['calls'])
        self.assertIn('Agent: codex', dashboard.html_document(data))
    cfg = {"backend": "victoriametrics", "query_url": "http://127.0.0.1:8428", "write_url": "http://127.0.0.1:8428/api/v1/import/prometheus", "instance": "unit-test"}

    def fake(self, config, url, body=None):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        expr = params["query"][0]
        if 'smr_openrouter_' in expr:
            return answer([])
        self.assertIn('instance="unit-test"', expr)
        if "query_range" in url:
            self.assertGreaterEqual(float(params["step"][0]), 60)
            return answer([({"outcome": "success"}, [[1700000000, "0.5"], [1700000060, "NaN"]])], True)
        if "_bucket" in expr:
            return answer([({"le": "1"}, [1700000000, "90"]),
                           ({"le": "2"}, [1700000000, "100"]),
                           ({"le": "+Inf"}, [1700000000, "100"])])
        if "smr_telemetry_coalesced_events_total" in expr or "smr_telemetry_dropped_events_total" in expr:
            self.assertIn("last_over_time(", expr)
            self.assertNotIn("increase(", expr)
            return answer([({}, [1700000000, "28"])])
        if "smr_jev_requests_total" in expr:
            return answer([({"outcome": "success"}, [1700000000, "100"])])
        return answer([({"reason": "rule:standard", "model": '<script>alert("x")</script>',
                         "user": "developer", "project": "repo-one", "tier": "standard", "applied": "true", "mode": "active"}, [1700000000, "100"])])

    def test_queries_and_summary(self):
        with mock.patch.object(dashboard, "request", side_effect=self.fake) as call:
            data = dashboard.query_stats(self.cfg, 7)
        self.assertLessEqual(call.call_count, 32)
        self.assertEqual(call.call_count, len(data["series"]))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["summary"]["error_share"], 0)
        self.assertEqual(data["summary"]["applied"], 100)
        self.assertEqual(data["summary"]["coalesced_events"], 28)
        self.assertEqual(data["summary"]["dropped_events"], 28)
        self.assertEqual(data["summary"]["by_tier"], {"standard": 100})
        self.assertEqual(data["summary"]["by_project"], {"repo-one": 100})
        self.assertEqual(data["summary"]["by_user"], {"developer": 100})
        self.assertEqual(data["summary"]["by_reason"], {"rule:standard": 100})
        self.assertEqual(data["summary"]["by_model"], {'<script>alert("x")</script>': 100})
        self.assertIn("coalesced lifetime 28", dashboard.format_summary(data))
        self.assertAlmostEqual(data["summary"]["jev_p95_seconds"], 1.5)
        self.assertIsNone(data["series"]["request_rate"][0]["points"][1][1])
        self.assertNotIn("query_url", json.dumps(data))

    def test_empty_errors_and_zero_are_distinct(self):
        def empty(config, url, body=None):
            return answer([], "query_range" in url)
        with mock.patch.object(dashboard, "request", side_effect=empty):
            data = dashboard.query_stats(self.cfg)
        self.assertEqual(data["status"], "no_data")
        self.assertIsNone(data["summary"]["calls"])
        with mock.patch.object(dashboard, "request", side_effect=RuntimeError("secret-token url")):
            data = dashboard.query_stats(self.cfg)
        self.assertEqual(data["status"], "error")
        self.assertNotIn("secret-token", json.dumps(data))
        self.assertIsNone(data["summary"]["jev_errors"])
        def partial(config, url, body=None):
            if "query_range" in url:
                raise RuntimeError("failed")
            return answer([({}, [1700000000, "0"])])
        with mock.patch.object(dashboard, "request", side_effect=partial):
            data = dashboard.query_stats(self.cfg)
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["summary"]["calls"], 0)

    def test_invalid_data_bounds(self):
        for days in (0, 91, -1, 1.5, True):
            with self.assertRaises(ValueError):
                dashboard.query_stats(self.cfg, days)
        for payload in ({"status": "error", "error": "secret"}, {"status": "success", "data": []}):
            with self.assertRaises(ValueError):
                dashboard._decode(json.dumps(payload), False)
        with self.assertRaises(ValueError):
            dashboard._decode(answer([({}, [0, "1"])] * 121), False)
        with self.assertRaises(ValueError):
            dashboard._decode(answer([({}, [[0, "1"]] * 242)], True), True)
        with self.assertRaises(ValueError):
            dashboard._decode(answer([({"a": "x" * 257}, [0, "1"])]), False)

    def test_project_exact_filter_and_aggregate_cohorts(self):
        for project in ("/private/repo", 'bad"project', "", 42):
            with self.assertRaises(ValueError):
                dashboard.query_stats(self.cfg, project=project)
        def fetch(config, url, body=None):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["query"][0]
            if "smr_telemetry_" in query or "smr_openrouter_" in query or "smr_hook_version_" in query:
                self.assertNotIn("project=", query)
            else:
                self.assertIn('project="repo-one"', query)
            return self.fake(config, url, body)
        with mock.patch.object(dashboard, "request", side_effect=fetch):
            data = dashboard.query_stats(self.cfg, project="repo-one")
        self.assertEqual(data["project"], "repo-one")
        self.assertEqual(data["summary"]["by_project"], {"repo-one": 100})
        self.assertNotIn("/private/", json.dumps(data))

    def test_user_exact_filter_and_health_scope(self):
        for user in ("/private/user", 'bad"user', "", 42):
            with self.assertRaises(ValueError):
                dashboard.query_stats(self.cfg, user=user)
        def fetch(config, url, body=None):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["query"][0]
            if "smr_telemetry_" in query or "smr_openrouter_" in query:
                self.assertNotIn("user=", query)
            else:
                self.assertIn('user="developer"', query)
            return self.fake(config, url, body)
        with mock.patch.object(dashboard, "request", side_effect=fetch):
            data = dashboard.query_stats(self.cfg, user="developer")
        self.assertEqual(data["user"], "developer")
        self.assertEqual(data["summary"]["by_user"], {"developer": 100})

    def test_real_http_empty_and_failure(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            status = 200
            paths = []

            def do_GET(self):
                self.paths.append(self.path)
                self.send_response(self.status)
                self.end_headers()
                self.wfile.write(answer([], "query_range" in self.path))

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = dict(self.cfg, query_url=f"http://127.0.0.1:{server.server_port}/select/7/prometheus")
        try:
            self.assertEqual(dashboard.query_stats(config)["status"], "no_data")
            self.assertTrue(all(p.startswith("/select/7/prometheus/api/v1/query") for p in Handler.paths))
            Handler.status = 503
            self.assertEqual(dashboard.query_stats(config)["status"], "error")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_script_free_report_escapes_server_labels(self):
        with mock.patch.object(dashboard, "request", side_effect=self.fake):
            data = dashboard.query_stats(self.cfg)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            dashboard.render_html(data, output)
            html = output.read_text()
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            output.chmod(0o644)
            dashboard.render_html(data, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("http://127.0.0.1", html)
        self.assertIn("Content-Security-Policy", html)
        self.assertIn("<svg", html)
        self.assertIn("Selection share is not cost or quality evidence", html)
        self.assertIn("Coalesced timing · lifetime</td><td>28", html)

    def test_chart_does_not_join_missing_timestamps(self):
        rows = [{"labels": {}, "points": [[0, 1], [60, 2], [300, 3], [360, 4]]}]
        result = dashboard._chart(rows, 0, 360, 60)
        self.assertEqual(result.count("<polyline"), 2)
        rows[0]["points"] = [[0, 1], [60, None], [120, 2]]
        self.assertEqual(dashboard._chart(rows, 0, 120, 60).count("<polyline"), 2)

    def test_cost_account_scope_and_stale_failed_snapshot(self):
        captured = []
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            captured.append(expression)
            if 'smr_openrouter_' in expression:
                self.assertIn('account="shared"', expression)
                self.assertNotIn('instance=', expression)
                for label in ('project=', 'user=', 'agent='):
                    self.assertNotIn(label, expression)
                values = {'account_balance_usd': 9.5, 'key_limit_remaining_usd': 8} if '_usd' in expression else {
                    'key_limit_remaining_available': 0, 'key_balance_probe_success': 0,
                    'key_last_success_timestamp_seconds': 1699999000,
                    'account_balance_probe_success': 1, 'account_last_success_timestamp_seconds': 1699999500}
                return answer([({'__name__': 'smr_openrouter_' + key, 'account': 'shared'}, [1700000000, str(value)]) for key, value in values.items()])
            if 'query_range' in url:
                return answer([], True)
            value = 0.000003 if 'smr_jev_cost_usd_total' in expression else 3 if 'known_cost' in expression else 1 if 'unpriced' in expression else None
            return answer([] if value is None else [({}, [1700000000, str(value)])])
        with mock.patch.object(dashboard, 'request', side_effect=respond), mock.patch.object(dashboard.time, 'time', return_value=1700000000):
            result = dashboard.query_stats(self.cfg, project='repo', user='dev', agent='codex', account='shared')
        summary = result['summary']
        self.assertEqual(summary['jev_cost_usd'], .000003)
        self.assertEqual(summary['jev_cost_coverage'], .75)
        self.assertEqual(summary['accounts']['shared']['key_age_seconds'], 1000)
        self.assertIsNone(summary['accounts']['shared']['key_limit_remaining_usd'])
        self.assertEqual(summary['accounts']['shared']['account_balance_usd'], 9.5)
        rendered = dashboard.html_document(result)
        self.assertIn('$0.000003', rendered)
        self.assertIn('failed / 1,000 s', rendered)
        self.assertTrue(any('3600 * sum(rate(' in expression for expression in captured))

    def test_cost_query_failure_does_not_become_zero_coverage(self):
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'known_cost' in expression:
                raise RuntimeError('unavailable')
            if 'unpriced' in expression:
                return answer([({}, [1700000000, '3'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            result = dashboard.query_stats(self.cfg)
        self.assertIsNone(result['summary']['jev_cost_coverage'])
        self.assertIsNone(result['summary']['jev_cost_usd'])

    def test_tokens_lookup_zero_missing_invalid_and_cohorts(self):
        values = {'jev_requests_total': 3, 'jev_input_tokens_total': 0, 'jev_input_known_token_requests_total': 2,
                  'jev_input_unknown_token_requests_total': 1, 'jev_output_tokens_total': 'NaN',
                  'jev_output_unknown_token_requests_total': 3,
                  'claude_model_lookup_requests_total': 2, 'claude_model_lookup_read_attempts_total': 3,
                  'claude_model_lookup_bytes_read_total': 1024, 'claude_model_lookup_duration_seconds_sum': .015,
                  'claude_model_lookup_api_input_tokens_total': 0,
                  'claude_model_lookup_api_output_tokens_total': 0, 'claude_model_lookup_cost_usd_total': 0}
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'query_range' in url:
                return answer([], True)
            if 'smr_telemetry_' not in expression and 'smr_openrouter_' not in expression:
                for label in ('instance="unit-test"', 'user="dev"', 'agent="claude"'):
                    self.assertIn(label, expression)
                if 'smr_hook_version_' not in expression:
                    self.assertIn('project="repo"', expression)
            for name, value in values.items():
                if 'smr_' + name + '{' in expression:
                    return answer([({}, [1700000000, str(value)])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            result = dashboard.query_stats(self.cfg, project='repo', user='dev', agent='claude')
        s = result['summary']
        self.assertEqual(s['jev_input_tokens'], 0)
        self.assertEqual(s['jev_input_token_coverage'], 2 / 3)
        self.assertIsNone(s['jev_output_tokens'])
        self.assertEqual(s['jev_output_token_coverage'], 0)
        self.assertEqual(s['claude_model_lookup_cost_usd'], 0)
        self.assertEqual(s['claude_model_lookup_duration_seconds'], .015)
        self.assertIn('Jev input tokens · reported: 0', dashboard.format_summary(result))
        self.assertIn('Claude model lookup · API spend</td><td>$0.000000', dashboard.html_document(result))
        values['jev_input_known_token_requests_total'] = 'NaN'
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            invalid = dashboard.query_stats(self.cfg, project='repo', user='dev', agent='claude')
        self.assertIsNone(invalid['summary']['jev_input_token_coverage'])
        values.clear()
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            empty = dashboard.query_stats(self.cfg, project='repo', user='dev', agent='claude')
        for key in ('jev_input_tokens', 'jev_input_token_coverage', 'claude_model_lookup_cost_usd', 'claude_model_lookup_requests'):
            self.assertIsNone(empty['summary'][key])

    def test_token_coverage_query_failure_is_unknown(self):
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'smr_jev_input_known_token_requests_total' in expression:
                raise RuntimeError('unavailable')
            if 'smr_jev_input_unknown_token_requests_total' in expression:
                return answer([({}, [1700000000, '3'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond):
            result = dashboard.query_stats(self.cfg)
        self.assertEqual(result['status'], 'partial')
        self.assertIsNone(result['summary']['jev_input_token_coverage'])

    def test_token_coverage_includes_legacy_requests_and_rejects_bad_denominators(self):
        cases = [(10, 1, 0, .1, 9), (10, None, None, 0, 10), (1, 1, 0, 1, 0),
                 (0, None, None, None, 0), (None, 1, None, None, None),
                 (1, 2, 0, None, None), (2, 1, 2, None, None),
                 ('NaN', 1, 0, None, None), (-1, 0, 0, None, None)]
        for requests, known, unknown, coverage, unmeasured in cases:
            with self.subTest(requests=requests, known=known, unknown=unknown):
                values = {'jev_requests_total': requests, 'jev_input_known_token_requests_total': known,
                          'jev_input_unknown_token_requests_total': unknown, 'jev_input_tokens_total': 200}
                def respond(config, url, body=None):
                    if 'query_range' in url:
                        return answer([], True)
                    expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
                    for name, value in values.items():
                        if 'smr_' + name + '{' in expression and value is not None:
                            return answer([({}, [1700000000, str(value)])])
                    return answer([])
                with mock.patch.object(dashboard, 'request', side_effect=respond):
                    result = dashboard.query_stats(self.cfg)
                self.assertEqual(result['summary']['jev_input_token_coverage'], coverage)
                self.assertEqual(result['summary']['jev_input_unknown_token_requests'], unmeasured)
                self.assertEqual(result['summary']['jev_input_tokens'], 200)
        doc = json.loads((PLUGIN / 'grafana' / 'subagent-model-router.json').read_text())
        panel = next(p for p in doc['panels'] if p['id'] == 38)
        for target in panel['targets']:
            self.assertIn('smr_jev_requests_total', target['expr'])
            self.assertIn(' <= ', target['expr'])

    def test_hook_versions_use_hook_time_not_export_and_ignore_project(self):
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'smr_hook_version_last_seen_timestamp_seconds' in expression:
                self.assertNotIn('project=', expression)
                for label in ('instance="unit-test"', 'user="dev"', 'agent="claude"'):
                    self.assertIn(label, expression)
                self.assertIn('max by (instance,host,user,agent,plugin_version,agent_version)', expression)
                labels = dict(instance='unit-test', host='host-a', user='dev', agent='claude')
                return answer([(dict(labels, plugin_version='9.0'), [1000, '100']),
                               (dict(labels, plugin_version='1.0'), [1000, '200']),
                               (dict(labels, host='host-b', plugin_version='2.0'), [1000, '150']),
                               (dict(labels, host='', plugin_version='3.0'), [1000, '950'])])
            if 'smr_calls_total' in expression and 'query_range' not in url:
                return answer([({'user': 'dev', 'agent': 'claude'}, [1000, '3'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond), mock.patch.object(dashboard.time, 'time', return_value=1000):
            data = dashboard.query_stats(self.cfg, project='repo', user='dev', agent='claude')
        rows = data['summary']['hook_versions']
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['plugin_version'], '1.0')
        self.assertTrue(rows[0]['latest_observed'])
        self.assertEqual(rows[0]['age_seconds'], 800)
        self.assertFalse(rows[1]['latest_observed'])
        self.assertTrue(rows[2]['latest_observed'])
        self.assertEqual(data['summary']['hook_version_metadata_gaps'], 3)
        self.assertEqual(data['summary']['hook_version_mixed_reporters'], 1)
        self.assertIn('historical', dashboard.html_document(data))
        self.assertIn('independent of project', dashboard.format_summary(data))

    def test_version_only_other_project_is_not_routing_data(self):
        def respond(config, url, body=None):
            if 'smr_hook_version_' in urllib.parse.unquote(url):
                return answer([({'instance': 'unit-test', 'host': 'host', 'user': 'dev', 'agent': 'claude',
                                 'plugin_version': '1.0'}, [1000, '900'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond), mock.patch.object(dashboard.time, 'time', return_value=1000):
            data = dashboard.query_stats(self.cfg, project='empty')
        self.assertEqual(data['status'], 'no_data')
        self.assertEqual(len(data['summary']['hook_versions']), 1)
        self.assertIsNone(data['summary']['calls'])

    def test_client_versions_do_not_collapse_and_legacy_remains_unknown(self):
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'smr_hook_version_' in expression:
                self.assertIn('plugin_version,agent_version)', expression)
                labels = dict(instance='unit-test', host='host', user='dev', agent='codex', plugin_version='0.4.8')
                return answer([(labels, [1000, '100']),
                               (dict(labels, agent_version='0.120.0'), [1000, '200']),
                               (dict(labels, agent_version='0.121.0'), [1000, '300'])])
            return answer([], 'query_range' in url)
        with mock.patch.object(dashboard, 'request', side_effect=respond), mock.patch.object(dashboard.time, 'time', return_value=1000):
            data = dashboard.query_stats(self.cfg)
        versions = data['summary']['hook_versions']
        self.assertEqual([v['agent_version'] for v in versions], ['0.121.0', '0.120.0', 'unknown'])
        self.assertEqual([v['latest_observed'] for v in versions], [True, False, False])
        self.assertEqual(data['summary']['hook_version_mixed_reporters'], 1)
        self.assertIn('plugin=0.4.8; client=unknown', dashboard.format_summary(data))
        self.assertIn('<th>Client version</th>', dashboard.html_document(data))
        self.assertIn('0.121.0', dashboard.html_document(data))

    def test_fresh_account_snapshot_beats_higher_stale_balance(self):
        def respond(config, url, body=None):
            expression = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
            if 'smr_openrouter_' not in expression:
                return answer([], 'query_range' in url)
            self.assertNotIn('max by', expression)
            snapshots = {
                'stopped': dict(account_balance_usd=100, account_last_success_timestamp_seconds=100,
                                account_last_attempt_timestamp_seconds=100, account_balance_probe_success=1,
                                key_limit_remaining_usd=80, key_limit_remaining_available=1,
                                key_last_success_timestamp_seconds=100),
                'active': dict(account_balance_usd=5, account_last_success_timestamp_seconds=200,
                               account_last_attempt_timestamp_seconds=200, account_balance_probe_success=1,
                               key_limit_remaining_usd=80, key_limit_remaining_available=0,
                               key_last_success_timestamp_seconds=200, key_usage_monthly_usd=40, key_usage_monthly_available=0),
                'failed': dict(account_last_attempt_timestamp_seconds=300, account_balance_probe_success=0)}
            values = []
            for instance, snapshot in snapshots.items():
                for name, value in snapshot.items():
                    if name.endswith('_usd') == ('_usd' in expression):
                        values.append(({'__name__': 'smr_openrouter_' + name, 'account': 'shared', 'instance': instance}, [400, str(value)]))
            return answer(values)
        with mock.patch.object(dashboard, 'request', side_effect=respond), mock.patch.object(dashboard.time, 'time', return_value=400):
            result = dashboard.query_stats(self.cfg, account='shared')
        account = result['summary']['accounts']['shared']
        self.assertEqual(account['account_balance_usd'], 5)
        self.assertEqual(account['account_age_seconds'], 200)
        self.assertEqual(account['account_balance_probe_success'], 0)
        self.assertIsNone(account['key_limit_remaining_usd'])
        self.assertIsNone(account['key_usage_monthly_usd'])

    def test_dashboard_import_structure_and_metrics(self):
        doc = json.loads((PLUGIN / "grafana" / "subagent-model-router.json").read_text())
        self.assertEqual(doc["uid"], "subagent-model-router")
        ids = [p["id"] for p in doc["panels"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(doc["templating"]["list"][0]["type"], "datasource")
        project = next(v for v in doc["templating"]["list"] if v["name"] == "project")
        self.assertIn('instance=~"$instance"', project["definition"])
        self.assertIn('user=~"$user"', project["definition"])
        self.assertTrue(any(v["name"] == "user" for v in doc["templating"]["list"]))
        for panel in doc["panels"]:
            for target in panel.get("targets", []):
                if 'smr_openrouter_' in target['expr']:
                    self.assertIn('account=~"$account"', target['expr'])
                    for variable in ('$project', '$user', '$instance', '$agent'):
                        self.assertNotIn(variable, target['expr'])
                    self.assertNotIn('sum(', target['expr'])
                    if '_usd' in target['expr']:
                        self.assertIn('and on (instance,account)', target['expr'])
                        self.assertIn('_last_success_timestamp_seconds', target['expr'])
                        self.assertTrue(target['expr'].startswith('min by (account)'))
                    continue
                self.assertIn('instance=~"$instance"', target["expr"])
                if "smr_hook_version_" in target["expr"]:
                    self.assertIn('plugin_version,agent_version)', target['expr'])
                    self.assertIn('agent=~"$agent"', target["expr"])
                    self.assertIn('user=~"$user"', target["expr"])
                    self.assertNotIn('$project', target["expr"])
                    continue
                if "smr_telemetry_" not in target["expr"]:
                    self.assertIn('agent=~"$agent"', target["expr"])
                    self.assertIn('project=~"$project"', target["expr"])
                    self.assertIn('user=~"$user"', target["expr"])
                else:
                    self.assertNotIn("$project", target["expr"])
                    self.assertNotIn("$user", target["expr"])
                self.assertIn("smr_", target["expr"])


if __name__ == "__main__":
    unittest.main()
