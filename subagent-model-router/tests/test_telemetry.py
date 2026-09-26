"""Aggregate outbox tests: local HTTP only, no accounts or production files."""
import concurrent.futures
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

SPEC = importlib.util.spec_from_file_location("router_telemetry", Path(__file__).resolve().parents[1] / "lib/router_telemetry.py")
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)


@contextlib.contextmanager
def server(status=204, delay=0, redirect=None):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, self.headers.get("Authorization"), self.rfile.read(int(self.headers.get("Content-Length", 0)))))
            if delay:
                time.sleep(delay)
            self.send_response(status)
            if redirect:
                self.send_header("Location", redirect)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(httpd.server_port), seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


@contextlib.contextmanager
def mocked_transport(**options):
    """Keep HTTP mocked until every exchange worker has actually exited."""
    workers = []
    thread_class = threading.Thread

    def spawn(*args, **kwargs):
        worker = thread_class(*args, **kwargs)
        workers.append(worker)
        return worker

    with mock.patch.object(telemetry.urllib.request.OpenerDirector, "open", **options) as send, \
            mock.patch.object(telemetry.threading, "Thread", side_effect=spawn):
        try:
            yield send
        finally:
            for worker in workers:
                worker.join(timeout=10)
                if worker.is_alive():
                    raise AssertionError("mocked transport worker did not exit")


class TelemetryTests(unittest.TestCase):
    def assert_transport_deadline(self, call, error):
        release = threading.Event()

        def pending(*args, **kwargs):
            # Completion cannot race the caller's timeout under CPU contention.
            # Safety cap also terminates this test if production stops timing out.
            release.wait(timeout=10)
            raise OSError("synthetic blocked transport")

        with mocked_transport(side_effect=pending) as send:
            started = time.monotonic()
            try:
                with self.assertRaisesRegex(telemetry.TelemetryError, error):
                    call()
                self.assertLess(time.monotonic() - started, 5)
            finally:
                release.set()
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["timeout"], .1)

    def test_effective_effort_and_unknown_are_not_inheritance_sentinels(self):
        for changes, expected in [({'effort': 'inherit', 'session_effort': 'high'}, 'high'),
                                  ({'effort': 'low', 'mode': 'shadow', 'session_effort': 'max'}, 'max'),
                                  ({'effort': 'low', 'actual_effort': None}, 'unknown'),
                                  ({'effort': 'inherit'}, 'unknown')]:
            call = next(k for k in telemetry._points(self.cfg, dict(self.record, **changes), .1)
                        if k.startswith('smr_calls_total{'))
            self.assertIn('effort="' + expected + '"', call)
            self.assertNotIn('effort="inherit"', call)
            self.assertNotIn('effort="unchanged"', call)
    def test_real_model_for_inherited_and_shadow_calls(self):
        for selected, mode, expected in [('inherit', 'active', 'gpt-6-astra'),
                                         ('gpt-5.6-luna', 'shadow', 'gpt-6-astra'),
                                         ('gpt-5.6-luna', 'active', 'gpt-5.6-luna')]:
            row = dict(self.record, model=selected, mode=mode, session_model='gpt-6-astra')
            call = next(k for k in telemetry._points(self.cfg, row, .1) if k.startswith('smr_calls_total{'))
            self.assertIn('model="' + expected + '"', call)
            self.assertNotIn('model="inherit"', call)
            if mode == 'shadow':
                self.assertIn('recommended_model="gpt-5.6-luna"', call)
        call = next(k for k in telemetry._points(self.cfg, dict(self.record, model='inherit'), .1)
                    if k.startswith('smr_calls_total{'))
        self.assertIn('model="unknown"', call)

    def test_old_model_counters_not_reexported_or_relabelled(self):
        self.enqueue()
        db = self.connection()
        old = 'smr_calls_total{model="inherit"}'
        db.execute('INSERT INTO series(name,value,born) VALUES(?,?,?)', (old, 12, 1))
        payload, stamp, revision = telemetry._prepare(db, self.cfg)
        self.assertNotIn(old.encode(), payload)
        db.execute('UPDATE pending SET payload=?', (payload + (old + ' 12 1\n').encode(),))
        retried = telemetry._prepare(db, self.cfg)
        self.assertEqual(retried, (payload, stamp, revision))
        self.assertEqual(telemetry._prepare(db, self.cfg), retried)
        db.close()
    def setUp(self):
        # Caller may choose its own private scratch root; never default to /tmp.
        root = Path(os.environ.get("TMPDIR", "/var/tmp/agent-plugins-vm/transport"))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = Path(tempfile.mkdtemp(prefix="telemetry-", dir=root))
        self.addCleanup(shutil.rmtree, self.root)
        self.cfg = telemetry.validate_config(dict(backend="victoriametrics", write_url="http://127.0.0.1:1/api/v1/import/prometheus",
                                                  query_url="http://127.0.0.1:1", instance="test", flush_interval_seconds=.1,
                                                  timeout_seconds=.1, max_queue_events=2))
        self.record = dict(agent="codex", mode="active", provider="typesafe", reason="rule:light", tier="light",
                           model="gpt-5.6-luna", effort="low", applied=True, latency_ms=150,
                           answers={"tier": {"light": .8, "standard": .15, "heavy": .05}},
                           description="PRIVATE-TASK", cwd="PRIVATE-CWD", session_id="PRIVATE-SESSION",
                           request_id="PRIVATE-REQUEST", state_sha256="PRIVATE-HASH")

    def enqueue(self, **kwargs):
        return telemetry.enqueue(self.cfg, self.record, .2, state_dir=self.root, **kwargs)

    def connection(self):
        return telemetry._db(self.cfg, self.root)

    def test_config_validation_no_credentials_queries_fragments(self):
        for url in ("http://user:secret@host/api/v1/import/prometheus", "http://host/api/v1/import/prometheus?token=x",
                    "http://host/api/v1/import/prometheus#secret", "file:///api/v1/import/prometheus", "http://host:bad/api/v1/import/prometheus"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                telemetry.validate_config(dict(self.cfg, write_url=url))
        for key, value in (("timeout_seconds", float("nan")), ("max_queue_events", 2.5), ("instance", 'x"}\nsecret')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                telemetry.validate_config(dict(self.cfg, **{key: value}))

    def test_only_aggregates_stored_and_exported(self):
        self.assertTrue(self.enqueue())
        db = self.connection()
        try:
            payload, _, _ = telemetry._prepare(db, self.cfg)
        finally:
            db.close()
        for path in self.root.iterdir():
            data = path.read_bytes()
            self.assertNotIn(b"PRIVATE-", data)
            self.assertNotIn(b"description", data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"PRIVATE-", payload)
        self.assertNotIn(b"session", payload)
        self.assertFalse(list(self.root.glob("*.jsonl")))
        self.assertIn(b'smr_calls_total{', payload)
        self.assertIn(b'applied="true"', payload)

    def test_histograms_cumulative_with_infinite_bucket(self):
        self.enqueue()
        db = self.connection()
        try:
            rows = dict(db.execute("SELECT name,value FROM series"))
        finally:
            db.close()
        buckets = {}
        for name, value in rows.items():
            if name.startswith("smr_jev_request_duration_seconds_bucket"):
                le = name.split('le="')[1].split('"')[0]
                buckets[float(le)] = value
        values = [buckets[k] for k in sorted(buckets)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(buckets[float("inf")], 1)
        self.assertEqual(next(v for k, v in rows.items() if k.startswith("smr_jev_request_duration_seconds_sum")), .15)
        self.assertEqual(next(v for k, v in rows.items() if k.startswith("smr_jev_request_duration_seconds_count")), 1)

    def test_bounded_queue_coalesces_without_losing_counters(self):
        for _ in range(30):
            self.assertTrue(self.enqueue())
        state = telemetry.snapshot(self.cfg, state_dir=self.root)
        self.assertEqual(state["pending_events"], 2)
        self.assertEqual(state["coalesced_events"], 28)
        self.assertEqual(state["dropped_events"], 0)
        db = self.connection()
        try:
            self.assertEqual(db.execute("SELECT value FROM series WHERE name LIKE 'smr_calls_total%'").fetchone()[0], 30)
            self.assertEqual(db.execute("SELECT count(*) FROM pending").fetchone()[0], 0)
        finally:
            db.close()

    def test_concurrent_writes_preserve_counts(self):
        self.enqueue()  # initialize schema before the concurrent workload
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.enqueue(), range(40)))
        # The hook deliberately has a finite lock budget. Every accepted write
        # must survive contention exactly once; rejected writes return False.
        self.assertGreater(sum(results), 0)
        self.assertEqual(telemetry.snapshot(self.cfg, state_dir=self.root)["revision"], 1 + sum(results))

    def test_ambiguous_delivery_retries_identical_payload_before_new_data(self):
        self.enqueue()
        sent = []

        def exchange(cfg, url, body=None):
            sent.append(body)
            if len(sent) == 1:
                raise telemetry.TelemetryError("timeout")
            return b""

        with mock.patch.object(telemetry, "request", side_effect=exchange):
            self.assertFalse(telemetry.flush_once(self.cfg, state_dir=self.root))
            self.enqueue()
            self.assertTrue(telemetry.flush_once(self.cfg, state_dir=self.root))
            self.assertEqual(sent[0], sent[1])
            state = telemetry.snapshot(self.cfg, state_dir=self.root)
            self.assertEqual(state["pending_events"], 1)
            self.assertTrue(telemetry.flush_once(self.cfg, state_dir=self.root))
            self.assertNotEqual(sent[1], sent[2])
        self.assertEqual(telemetry.snapshot(self.cfg, state_dir=self.root)["delivered_revision"], 2)
        self.assertEqual(telemetry.snapshot(self.cfg, state_dir=self.root)["pending_bytes"], 0)

    def test_new_series_have_zero_baseline_once(self):
        self.enqueue()
        sent = []
        with mock.patch.object(telemetry, "request", side_effect=lambda cfg, url, body: sent.append(body) or b""):
            telemetry.flush_once(self.cfg, state_dir=self.root)
            telemetry.flush_once(self.cfg, state_dir=self.root)
        first_calls = [line for line in sent[0].splitlines() if line.startswith(b"smr_calls_total")]
        later_calls = [line for line in sent[1].splitlines() if line.startswith(b"smr_calls_total")]
        self.assertEqual(len(first_calls), 2)
        self.assertEqual(len(later_calls), 1)
        self.assertEqual(first_calls[0].split()[-2], b"0")

    def test_slow_unreachable_endpoint_does_not_block_enqueue(self):
        with mock.patch.object(telemetry, "request", side_effect=AssertionError("hook must not use HTTP")) as http:
            self.assertTrue(self.enqueue())
            http.assert_not_called()  # verifies isolation independently of disk/runner scheduling
        with server(delay=.3) as (url, seen):
            started = time.monotonic()
            with self.assertRaisesRegex(telemetry.TelemetryError, "timeout|network"):
                telemetry.request(self.cfg, url + "/api/v1/import/prometheus", b"metric 1\n")
            self.assertLess(time.monotonic() - started, .25)

    def test_auth_no_redirect_and_redacted_failure(self):
        token = self.root / "token"
        token.write_text("TEST-BEARER-ONLY")
        token.chmod(0o600)
        cfg = dict(self.cfg, token_file=str(token), timeout_seconds=1)
        with server() as (target, target_seen):
            with server(status=307, redirect=target) as (url, seen):
                with self.assertRaisesRegex(telemetry.TelemetryError, "^http_307$"):
                    telemetry.request(cfg, url, b"metric 1\n")
                self.assertEqual(seen[0][1], "Bearer TEST-BEARER-ONLY")
            self.assertEqual(target_seen, [])
        token.chmod(0o644)
        with self.assertRaisesRegex(telemetry.TelemetryError, "^token_permissions$"):
            telemetry.request(cfg, "http://127.0.0.1:1", b"x")

    def test_single_worker_lock_and_config_change_stop(self):
        fd = telemetry._lock(self.cfg, self.root)
        try:
            with mock.patch.object(telemetry, "flush_once", side_effect=AssertionError("locked")):
                self.assertEqual(telemetry.worker(self.cfg, state_dir=self.root, max_runtime_seconds=0), 0)
        finally:
            os.close(fd)
        with mock.patch.object(telemetry, "flush_once", side_effect=AssertionError("disabled")):
            self.assertEqual(telemetry.worker(self.cfg, state_dir=self.root,
                                             reload_config=lambda: dict(self.cfg, backend="off")), 0)

    def test_contended_database_has_bounded_hook_delay(self):
        self.enqueue()
        db = self.connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            self.assertFalse(self.enqueue())
            # SQLite has a 100 ms busy timeout per operation; shared macOS CI
            # can deschedule this process between operations. Still require
            # return well before the hook's 10 s deadline, without waiting for unlock.
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            db.rollback()
            db.close()

    def test_second_connection_preserves_first_connections_process_locks(self):
        self.enqueue()
        first = self.connection()
        second = None
        path, _ = telemetry._paths(self.cfg, self.root)
        script = """
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], timeout=.05, isolation_level=None)
try:
    connection.execute('BEGIN IMMEDIATE')
except sqlite3.OperationalError as exc:
    print('blocked' if 'locked' in str(exc) else 'error')
else:
    print('acquired')
    connection.rollback()
finally:
    connection.close()
"""

        def probe():
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path)],
                                    capture_output=True, text=True, timeout=5, check=True)
            return result.stdout.strip()

        try:
            first.execute("BEGIN IMMEDIATE")
            self.assertEqual(probe(), "blocked")
            second = self.connection()
            self.assertEqual(probe(), "blocked")
            second.close()
            second = None
            self.assertEqual(probe(), "blocked")
            first.rollback()
            self.assertEqual(probe(), "acquired")
        finally:
            if second is not None:
                second.close()
            first.close()

    def test_database_symlink_is_rejected_without_touching_target(self):
        path, _ = telemetry._paths(self.cfg, self.root)
        target = self.root / "unrelated"
        target.write_text("keep")
        target.chmod(0o640)
        path.symlink_to(target)
        with self.assertRaisesRegex(telemetry.TelemetryError, "^state_permissions$"):
            self.connection()
        self.assertEqual(target.read_text(), "keep")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_detached_spawn_and_existing_worker_suppresses_spawn(self):
        command = ["python3", "/example/router", "telemetry-worker"]
        with mock.patch.object(telemetry.subprocess, "Popen") as spawn:
            self.assertTrue(self.enqueue(worker_command=command))
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            self.assertTrue(spawn.call_args.kwargs["close_fds"])
            spawn.reset_mock()
            fd = telemetry._lock(self.cfg, self.root)
            try:
                self.assertTrue(self.enqueue(worker_command=command))
                spawn.assert_not_called()
            finally:
                os.close(fd)

    def test_kick_spawns_without_writing_and_respects_running_worker(self):
        command = ["python3", "/example/router", "telemetry-worker"]
        with mock.patch.object(telemetry.subprocess, "Popen") as spawn:
            self.assertFalse(telemetry.kick(dict(self.cfg, backend="off"), command, state_dir=self.root))
            spawn.assert_not_called()
            self.assertTrue(telemetry.kick(self.cfg, command, state_dir=self.root))
            self.assertEqual(spawn.call_args.args[0], command)
            self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            self.assertEqual(telemetry.snapshot(self.cfg, state_dir=self.root)["revision"], 0)
            spawn.reset_mock()
            fd = telemetry._lock(self.cfg, self.root)
            try:
                self.assertTrue(telemetry.kick(self.cfg, command, state_dir=self.root))
                spawn.assert_not_called()
            finally:
                os.close(fd)

    def test_dns_timeout_is_wall_clock_bounded(self):
        self.assert_transport_deadline(
            lambda: telemetry.request(self.cfg, self.cfg["write_url"], b"x"), "^timeout$")

    def test_exported_health_is_aggregate_only(self):
        self.enqueue()
        db = self.connection()
        try:
            payload, _, _ = telemetry._prepare(db, self.cfg)
        finally:
            db.close()
        self.assertIn(b'smr_telemetry_pending_events{instance="test"} 1 ', payload)
        self.assertIn(b'smr_telemetry_last_success_timestamp_seconds{instance="test"} 0 ', payload)
        self.assertIn(b'smr_telemetry_coalesced_events_total{instance="test"} 0 ', payload)
        self.assertIn(b'smr_telemetry_dropped_events_total{instance="test"} 0 ', payload)

    def test_project_repositories_nested_directories_and_worktree_marker(self):
        first, second = self.root / "alpha", self.root / "beta"
        (first / ".git").mkdir(parents=True)
        (first / "src" / "deep").mkdir(parents=True)
        second.mkdir()
        (second / ".git").write_text("gitdir: ignored-sensitive-path")
        self.assertEqual(telemetry.resolve_project(str(first / "src" / "deep"), self.cfg), "alpha")
        self.assertEqual(telemetry.resolve_project(str(second), self.cfg), "beta")

    def test_project_overrides_longest_component_prefix_and_validation(self):
        cfg = telemetry.validate_config(dict(self.cfg, projects={str(self.root): "workspace", str(self.root / "repo"): "product"}))
        self.assertEqual(telemetry.resolve_project(str(self.root / "repo" / "src"), cfg), "product")
        self.assertEqual(telemetry.resolve_project(str(self.root / "repository"), cfg), "workspace")
        for mapping in ({"relative": "label"}, {str(self.root): "bad/label"}, {str(self.root): "bad\nlabel"}):
            with self.assertRaises(ValueError):
                telemetry.validate_config(dict(self.cfg, projects=mapping))

    def test_project_label_on_every_event_metric_and_no_path_leak(self):
        for project in ("alpha", "beta"):
            self.record["project"] = project
            self.assertTrue(self.enqueue())
        db = self.connection()
        try:
            payload, _, _ = telemetry._prepare(db, self.cfg)
            names = [row[0] for row in db.execute("SELECT name FROM series")]
        finally:
            db.close()

        self.assertTrue(all('project="alpha"' in name or 'project="beta"' in name for name in names))
        self.assertEqual(sum(name.startswith("smr_calls_total") for name in names), 2)
        self.assertNotIn(str(self.root).encode(), payload)
        self.assertTrue(all(b"project=" not in line for line in payload.splitlines() if line.startswith(b"smr_telemetry_")))
        self.record["project"] = "/private/path"
        self.assertTrue(self.enqueue())
        db = self.connection()
        try:
            self.assertFalse(any("/private/path" in row[0] for row in db.execute("SELECT name FROM series")))
        finally:
            db.close()

    def test_user_local_login_and_explicit_override(self):
        with mock.patch.object(telemetry.getpass, "getuser", return_value="kk573"):
            self.assertEqual(telemetry.resolve_user(self.cfg), "kk573")
            cfg = telemetry.validate_config(dict(self.cfg, user="csssr"))
            self.assertEqual(telemetry.resolve_user(cfg), "csssr")
        with mock.patch.object(telemetry.getpass, "getuser", side_effect=OSError):
            self.assertEqual(telemetry.resolve_user(self.cfg), "unknown")
        with self.assertRaises(ValueError):
            telemetry.validate_config(dict(self.cfg, user="/private/path"))

    def test_user_cohorts_are_separate_on_all_event_metrics(self):
        for user in ("kk573", "csssr"):
            self.record["user"] = user
            self.enqueue()
        db = self.connection()
        try:
            names = [row[0] for row in db.execute("SELECT name FROM series")]
        finally:
            db.close()
        self.assertEqual(sum(name.startswith("smr_calls_total") for name in names), 2)
        self.assertTrue(all('user="kk573"' in name or 'user="csssr"' in name for name in names))
    def test_errors_count_request_and_duration(self):
        self.record.update(reason="error:timeout", answers=None, tier=None, latency_ms=3000)
        self.enqueue()
        db = self.connection()
        try:
            keys = [r[0] for r in db.execute("SELECT name FROM series")]
        finally:
            db.close()
        self.assertTrue(any(k.startswith("smr_jev_requests_total") and 'outcome="timeout"' in k for k in keys))
        self.assertTrue(any(k.startswith("smr_jev_request_duration_seconds_count") for k in keys))
        self.assertFalse(any(k.startswith("smr_decision_probability") for k in keys))

    def test_cardinality_bound_records_drop_and_destination_isolation(self):
        self.enqueue()
        with mock.patch.object(telemetry, "MAX_SERIES", 1):
            self.record["model"] = "gpt-new"
            self.enqueue()
        self.assertEqual(telemetry.snapshot(self.cfg, state_dir=self.root)["dropped_events"], 1)
        changed = dict(self.cfg, instance="other")
        self.assertEqual(telemetry.snapshot(changed, state_dir=self.root)["revision"], 0)

    def test_cost_and_tokens_only_from_known_numeric_usage(self):
        for cost in (0, .0123):
            self.record["usage"] = dict(cost=cost, input_tokens=100, output_tokens=0)
            points = telemetry._points(self.cfg, self.record, .2)
            self.assertEqual(next(v for k, v in points.items() if k.startswith("smr_jev_cost_usd_total")), cost)
            self.assertTrue(any(k.startswith("smr_jev_known_cost_requests_total") for k in points))
            self.assertFalse(any(k.startswith("smr_jev_unpriced_requests_total") for k in points))
            self.assertEqual(next(v for k, v in points.items() if k.startswith("smr_jev_input_tokens_total")), 100)
            self.assertEqual(next(v for k, v in points.items() if k.startswith("smr_jev_output_tokens_total")), 0)
        for usage in (None, {}, {"cost": None}, {"cost": -1}, {"cost": True}, {"cost": float("nan")},
                      {"cost": ".1", "input_tokens": -1, "output_tokens": .5}):
            self.record.update(usage=usage, reason="error:timeout")
            points = telemetry._points(self.cfg, self.record, .2)
            self.assertTrue(any(k.startswith("smr_jev_unpriced_requests_total") for k in points))
            self.assertFalse(any(k.startswith(("smr_jev_cost_usd_total", "smr_jev_input_tokens_total", "smr_jev_output_tokens_total")) for k in points))
        self.record.update(latency_ms=None, usage={"cost": 10}, reason="excluded")
        self.assertFalse(any(k.startswith("smr_jev_") for k in telemetry._points(self.cfg, self.record, .2)))

    def balance_config(self):
        return telemetry.validate_config(dict(self.cfg, openrouter_balance=True, account="test-account"))

    def balance_rows(self):
        db = self.connection()
        try:
            return dict(db.execute("SELECT name,value FROM gauges"))
        finally:
            db.close()

    def test_balance_requires_explicit_alias_and_defaults_off(self):
        self.assertFalse(self.cfg["openrouter_balance"])
        for extra in ({"openrouter_balance": True}, {"openrouter_balance": "yes"}, {"account": "private/path"}):
            with self.assertRaises(ValueError):
                telemetry.validate_config(dict(self.cfg, **extra))
        with mock.patch.object(telemetry, "openrouter_request") as request:
            self.assertFalse(telemetry.probe_openrouter_balance(self.cfg, lambda: "unused", state_dir=self.root))
            request.assert_not_called()

    def test_balance_separate_account_and_key_values_throttled_durably(self):
        cfg = self.balance_config()
        def exchange(path, key, timeout):
            self.assertEqual(key, "PRIVATE-PROVIDER-KEY")
            return ({"usage": 2, "limit": 50, "limit_remaining": 48, "usage_daily": .1,
                     "usage_weekly": .4, "usage_monthly": 2, "label": "PRIVATE-ACCOUNT"}
                    if path.endswith("key") else {"total_credits": 100, "total_usage": 93})
        with mock.patch.object(telemetry, "openrouter_request", side_effect=exchange) as request, mock.patch.object(telemetry.time, "time", return_value=1000):
            self.assertTrue(telemetry.probe_openrouter_balance(cfg, lambda: "PRIVATE-PROVIDER-KEY", state_dir=self.root))
            self.assertFalse(telemetry.probe_openrouter_balance(cfg, lambda: "PRIVATE-PROVIDER-KEY", state_dir=self.root))
            self.assertEqual(request.call_count, 2)
        rows = self.balance_rows()
        for suffix, expected in (("key_limit_remaining_usd", 48), ("account_balance_usd", 7),
                                 ("key_usage_daily_usd", .1), ("key_balance_probe_success", 1),
                                 ("account_balance_probe_success", 1), ("account_last_success_timestamp_seconds", 1000)):
            self.assertEqual(rows[telemetry._metric("openrouter_" + suffix, dict(instance="test", account="test-account"))], expected)
        db = self.connection()
        try:
            payload, _, _ = telemetry._prepare(db, cfg)
        finally:
            db.close()
        balance_lines = [line for line in payload.splitlines() if line.startswith(b"smr_openrouter_")]
        self.assertEqual(len(balance_lines), len(rows))  # gauges have no synthetic zero
        for path in self.root.iterdir():
            self.assertNotIn(b"PRIVATE-", path.read_bytes())
        self.assertNotIn(b"PRIVATE-", payload)

    def test_balance_failure_retains_stale_value_and_null_limit_removes_old_gauge(self):
        cfg = self.balance_config()
        key = lambda: "fake-key"
        with mock.patch.object(telemetry, "openrouter_request", side_effect=[{"usage": 2, "limit": 5, "limit_remaining": 3}, {"total_credits": 100, "total_usage": 93}]), mock.patch.object(telemetry.time, "time", return_value=1000):
            telemetry.probe_openrouter_balance(cfg, key, state_dir=self.root)
        with mock.patch.object(telemetry, "openrouter_request", side_effect=[{"usage": 3, "limit": None, "limit_remaining": None}, telemetry.TelemetryError("PRIVATE-secret-error")]), mock.patch.object(telemetry.time, "time", return_value=1300):
            telemetry.probe_openrouter_balance(cfg, key, state_dir=self.root)
        rows = self.balance_rows()
        def value(name):
            return rows.get(telemetry._metric("openrouter_" + name, dict(instance="test", account="test-account")))
        self.assertIsNone(value("key_limit_usd"))
        self.assertIsNone(value("key_limit_remaining_usd"))
        self.assertEqual(value("key_limit_configured"), 0)
        self.assertEqual(value("key_limit_remaining_available"), 0)
        self.assertEqual(value("key_usage_usd"), 3)
        self.assertEqual(value("account_balance_usd"), 7)
        self.assertEqual(value("account_balance_probe_success"), 0)
        self.assertEqual(value("account_last_success_timestamp_seconds"), 1000)
        self.assertEqual(value("account_last_attempt_timestamp_seconds"), 1300)

    def test_balance_credentials_failure_is_redacted_and_restart_throttled(self):
        cfg = self.balance_config()
        with mock.patch.object(telemetry, "openrouter_request") as request, mock.patch.object(telemetry.time, "time", return_value=1000):
            telemetry.probe_openrouter_balance(cfg, mock.Mock(side_effect=ValueError("PRIVATE-secret")), state_dir=self.root)
            request.assert_not_called()
        with mock.patch.object(telemetry, "openrouter_request") as request, mock.patch.object(telemetry.time, "time", return_value=1299):
            telemetry.worker(cfg, state_dir=self.root, max_runtime_seconds=0, read_openrouter_key=lambda: "fake-key")
            request.assert_not_called()
        self.assertFalse(any("PRIVATE" in name for name in self.balance_rows()))
        self.assertFalse(any("balance_usd" in name for name in self.balance_rows()))

    def test_optional_period_usage_availability_clears_missing_and_null_values(self):
        cfg = self.balance_config()
        labels = dict(instance="test", account="test-account")
        initial = {"usage": 2, "usage_daily": .1, "usage_weekly": .4, "usage_monthly": 2}
        credits = {"total_credits": 100, "total_usage": 93}
        with mock.patch.object(telemetry, "openrouter_request", side_effect=[initial, credits]), mock.patch.object(telemetry.time, "time", return_value=1000):
            telemetry.probe_openrouter_balance(cfg, lambda: "key", state_dir=self.root)
        rows = self.balance_rows()
        for period in ("daily", "weekly", "monthly"):
            self.assertEqual(rows[telemetry._metric("openrouter_key_usage_" + period + "_available", labels)], 1)
        # Missing, explicit null, and a known zero must remain distinct.
        later = {"usage": 3, "usage_weekly": None, "usage_monthly": 0}
        with mock.patch.object(telemetry, "openrouter_request", side_effect=[later, credits]), mock.patch.object(telemetry.time, "time", return_value=1300):
            telemetry.probe_openrouter_balance(cfg, lambda: "key", state_dir=self.root)
        rows = self.balance_rows()
        for period in ("daily", "weekly"):
            self.assertEqual(rows[telemetry._metric("openrouter_key_usage_" + period + "_available", labels)], 0)
            self.assertNotIn(telemetry._metric("openrouter_key_usage_" + period + "_usd", labels), rows)
        self.assertEqual(rows[telemetry._metric("openrouter_key_usage_monthly_available", labels)], 1)
        self.assertEqual(rows[telemetry._metric("openrouter_key_usage_monthly_usd", labels)], 0)
        self.assertEqual(rows[telemetry._metric("openrouter_key_balance_probe_success", labels)], 1)
        with mock.patch.object(telemetry, "openrouter_request", side_effect=telemetry.TelemetryError("failed")), mock.patch.object(telemetry.time, "time", return_value=1600):
            telemetry.probe_openrouter_balance(cfg, lambda: "key", state_dir=self.root)
        failed_rows = self.balance_rows()
        for period in ("daily", "weekly", "monthly"):
            name = telemetry._metric("openrouter_key_usage_" + period + "_available", labels)
            self.assertEqual(failed_rows[name], rows[name])
        self.assertEqual(failed_rows[telemetry._metric("openrouter_key_last_success_timestamp_seconds", labels)], 1300)

    def test_openrouter_transport_fixed_origin_auth_no_redirect_and_deadline(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"data": {"usage": 2}}).encode()
        with mocked_transport(return_value=response) as send:
            self.assertEqual(telemetry.openrouter_request("/api/v1/key", "PROVIDER-ONLY", 5), {"usage": 2})
            req = send.call_args.args[0]
            self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/key")
            self.assertEqual(req.get_header("Authorization"), "Bearer PROVIDER-ONLY")
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(send.call_args.kwargs["timeout"], 5)
        with self.assertRaisesRegex(telemetry.TelemetryError, "^openrouter_path$"):
            telemetry.openrouter_request("https://other.example/api/v1/key", "PROVIDER-ONLY", .1)
        self.assert_transport_deadline(
            lambda: telemetry.openrouter_request("/api/v1/key", "PROVIDER-ONLY", .1), "^openrouter_timeout$")
        self.assertIsNone(telemetry._NoRedirect().redirect_request(None, None, 307, "", {}, "https://other.example"))

    def test_balance_worker_probes_then_flushes_without_hook_network(self):
        cfg = self.balance_config()
        with mock.patch.object(telemetry, "probe_openrouter_balance") as probe, mock.patch.object(telemetry, "flush_once", return_value=True) as flush:
            read = lambda: "test-key"
            telemetry.worker(cfg, state_dir=self.root, max_runtime_seconds=0, read_openrouter_key=read)
            probe.assert_called_once_with(cfg, read, state_dir=self.root)
            flush.assert_called_once_with(cfg, state_dir=self.root)

    def test_balance_success_remains_independent_when_key_endpoint_fails(self):
        cfg = self.balance_config()
        with mock.patch.object(telemetry, "openrouter_request", side_effect=[telemetry.TelemetryError("failure"), {"total_credits": 8, "total_usage": 9}]), mock.patch.object(telemetry.time, "time", return_value=1000):
            telemetry.probe_openrouter_balance(cfg, lambda: "key", state_dir=self.root)
        rows = self.balance_rows()
        labels = dict(instance="test", account="test-account")
        self.assertEqual(rows[telemetry._metric("openrouter_key_balance_probe_success", labels)], 0)
        self.assertEqual(rows[telemetry._metric("openrouter_account_balance_probe_success", labels)], 1)
        self.assertEqual(rows[telemetry._metric("openrouter_account_balance_usd", labels)], -1)

    def test_v1_migration_preserves_counters_and_pending_snapshot(self):
        self.enqueue()
        db = self.connection()
        try:
            pending = telemetry._prepare(db, self.cfg)
            db.execute("DROP TABLE gauges")
            db.execute("PRAGMA user_version=1")
        finally:
            db.close()
        db = self.connection()
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(telemetry._prepare(db, self.cfg), pending)
            self.assertEqual(db.execute("SELECT value FROM series WHERE name LIKE 'smr_calls_total%'").fetchone()[0], 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
