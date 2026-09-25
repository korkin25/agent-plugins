"""Hook/CLI storage dispatch; no live VictoriaMetrics or Jev."""
import io
import json
import sys
from unittest import mock

from test_router import Sandbox, agent_input, router


class TelemetryIntegrationTests(Sandbox):
    def test_off_stops_journal_without_disabling_routing(self):
        self.serve()
        self.write_config(telemetry={"backend": "off"})
        rc, out, err, _ = self.hook()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.routed_model(out), "haiku")
        self.assertFalse(self.journal.exists())

    def test_invalid_telemetry_does_not_disable_routing_or_restore_journal(self):
        self.serve()
        self.write_config(telemetry={"backend": "victoriametrics", "write_url": "invalid"})
        rc, out, err, _ = self.hook()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(self.routed_model(out), "haiku")
        self.assertFalse(self.journal.exists())
        rc, out, err, _ = self.run_router("stats")
        self.assertEqual(rc, 1)
        self.assertIn("invalid telemetry", err)

    def test_vm_dispatch_records_duration_without_journaling(self):
        import router_telemetry
        cfg = router.normalize_config({"telemetry": {
            "backend": "victoriametrics", "write_url": "http://127.0.0.1:8428/api/v1/import/prometheus",
            "query_url": "http://127.0.0.1:8428", "instance": "test"}})
        event = {"tool_name": "Agent", "tool_input": agent_input()}
        record = router.base_record(event, "claude")
        record.update(reason="rule:light", model="haiku", tier="light", mode="active")
        expected = {"systemMessage": "selection"}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(event).encode()))
        stdout = io.StringIO()
        try:
            with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout), \
                    mock.patch.object(sys, "stderr", io.StringIO()), \
                    mock.patch.object(router, "handle_event", return_value=(expected, record)), \
                    mock.patch.object(router, "load_config", return_value=cfg), \
                    mock.patch.object(router, "append_journal") as journal, \
                    mock.patch.object(router_telemetry, "enqueue", return_value=True) as enqueue:
                self.assertEqual(router.hook_main(), 0)
                sys.stderr.close()
            self.assertEqual(json.loads(stdout.getvalue()), expected)
            journal.assert_not_called()
            self.assertEqual(enqueue.call_args.args[0], cfg["telemetry"])
            exported = enqueue.call_args.args[1]
            self.assertEqual({k: v for k, v in exported.items() if k not in ("project", "user")},
                             dict(record, applied=False))
            self.assertTrue(exported["project"])
            self.assertTrue(exported["user"])
            self.assertGreaterEqual(enqueue.call_args.args[2], 0)
            self.assertEqual(enqueue.call_args.kwargs["worker_command"][-1], "telemetry-worker")
        finally:
            stdin.close()

    def test_stats_dispatches_vm_and_does_not_read_old_journal(self):
        import router_dashboard
        self.write_config(telemetry={"backend": "victoriametrics",
            "write_url": "http://127.0.0.1:8428/api/v1/import/prometheus",
            "query_url": "http://127.0.0.1:8428", "instance": "test"})
        data = {"status": "error", "summary": {}, "series": {}, "errors": {"calls": "unavailable"}}
        with mock.patch.dict("os.environ", self.env()), \
                mock.patch.object(router_dashboard, "query_stats", return_value=data) as query, \
                mock.patch.object(router, "cmd_local_stats") as local, \
                mock.patch.object(sys, "stdout", io.StringIO()), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(router.cmd_stats(3, as_json=True), 1)
            self.assertEqual(query.call_args.kwargs, {"days": 3})
            local.assert_not_called()

    def test_stats_rejects_unbounded_range(self):
        for value in ("0", "-1", "91"):
            rc, _, err, _ = self.run_router("stats", "--days", value)
            self.assertEqual(rc, 2)
            self.assertIn("between 1 and 90", err)

    def test_invalid_routing_config_does_not_restore_journal(self):
        self.write_config(mode="invalid", telemetry={"backend": "off"})
        rc, out, err, _ = self.hook()
        self.assertEqual((rc, out, err), (0, "", ""))
        self.assertFalse(self.journal.exists())

    def test_terminal_stats_are_in_output_without_file_or_browser(self):
        self.journal.parent.mkdir(parents=True)
        from datetime import datetime, timezone
        row = {"ts": datetime.now(timezone.utc).isoformat(), "agent": "codex", "reason": "explicit"}
        self.journal.write_text(json.dumps(row) + "\n")
        rc, out, err, _ = self.run_router("stats", "--days", "7", "--terminal")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("|", out)
        self.assertIn("codex", out)
        self.assertNotIn("Browser report", out)
        self.assertFalse(list(self.root.rglob("*.html")))

    def test_browser_report_keeps_terminal_output_and_no_html_file(self):
        import router_dashboard, router_browser, router_terminal
        self.write_config(telemetry={"backend": "victoriametrics",
            "write_url": "http://127.0.0.1:8428/api/v1/import/prometheus",
            "query_url": "http://127.0.0.1:8428", "instance": "test"})
        data = {"status": "ok", "summary": {}, "series": {}, "errors": {}}
        report = router_browser.BrowserReport("http://127.0.0.1:1234/random", 123456)
        output = io.StringIO()
        with mock.patch.dict("os.environ", self.env()), \
                mock.patch.object(router_dashboard, "query_stats", return_value=data) as query, \
                mock.patch.object(router_terminal, "format_terminal", return_value="VISIBLE DASHBOARD"), \
                mock.patch.object(router_dashboard, "html_document", return_value="<html>report</html>"), \
                mock.patch.object(router_browser, "start_report", return_value=report) as browser, \
                mock.patch.object(router_dashboard, "render_html") as save, \
                mock.patch.object(sys, "stdout", output):
            self.assertEqual(router.cmd_stats(7, terminal=True, browser=True, agent="codex"), 0)
        self.assertIn("VISIBLE DASHBOARD", output.getvalue())
        self.assertIn(report.url, output.getvalue())
        query.assert_called_once_with(mock.ANY, days=7, agent="codex")
        browser.assert_called_once_with("<html>report</html>", open_default=False)
        save.assert_not_called()

    def test_json_cannot_mix_browser_side_effects(self):
        rc, _, err, _ = self.run_router("stats", "--json", "--open")
        self.assertEqual(rc, 2)
        self.assertIn("cannot be combined", err)
