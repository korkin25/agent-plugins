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
        self.assertEqual(call.call_count, 11)
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
            if "smr_telemetry_" in query:
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
            if "smr_telemetry_" in query:
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
                self.assertIn('instance=~"$instance"', target["expr"])
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
