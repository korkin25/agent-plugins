"""Aggregate outbox tests: local HTTP only, no accounts or production files."""
import concurrent.futures
import contextlib
import importlib.util
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


class TelemetryTests(unittest.TestCase):
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
        with mock.patch.object(telemetry, "request", side_effect=AssertionError("hook must not use HTTP")):
            started = time.monotonic()
            self.assertTrue(self.enqueue())
            self.assertLess(time.monotonic() - started, .2)
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

    def test_dns_timeout_is_wall_clock_bounded(self):
        with mock.patch.object(telemetry.urllib.request.OpenerDirector, "open", side_effect=lambda *args, **kwargs: time.sleep(.4)):
            started = time.monotonic()
            with self.assertRaisesRegex(telemetry.TelemetryError, "^timeout$"):
                telemetry.request(self.cfg, self.cfg["write_url"], b"x")
            self.assertLess(time.monotonic() - started, .25)

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


if __name__ == "__main__":
    unittest.main()
