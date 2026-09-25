"""Temporary report delivery is local, bounded and leaves no report files."""
import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from unittest import mock
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import router_browser as browser


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.children = []
        original = subprocess.Popen

        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            return child

        self.patcher = mock.patch.object(browser.subprocess, "Popen", side_effect=spawn)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for child in self.children:
            browser._stop(child)

    def request(self, url, *, path=None, host=None, method="GET"):
        parsed = urlsplit(url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        try:
            connection.request(method, path or parsed.path, headers={"Host": host or parsed.netloc})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_html_exact_no_browser_by_default_and_fast_ack(self):
        html = "<!doctype html><p>Статистика</p>"
        started = time.monotonic()
        with mock.patch.object(browser, "_open_default") as opener:
            report = browser.start_report(html, ttl_seconds=3)
        self.assertLess(time.monotonic() - started, 2)
        opener.assert_not_called()
        self.assertFalse(report.default_browser_attempted)
        self.assertFalse(report.default_browser_opened)
        self.assertGreater(report.expires_at, time.time())
        status, headers, body = self.request(report.url)
        self.assertEqual(status, 200)
        self.assertEqual(body, html.encode())
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_wrong_path_host_and_file_routes_denied(self):
        report = browser.start_report("<p>private report</p>", ttl_seconds=5)
        port = urlsplit(report.url).port
        for path in ("/", "/etc/passwd", "/../router_browser.py", "/keys", "/proxy", urlsplit(report.url).path + "?export=1"):
            with self.subTest(path=path):
                status, _, body = self.request(report.url, path=path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"private report", body)
        for host in ("attacker.example", f"attacker.example:{port}", "127.0.0.1", f"127.0.0.1:{port + 1}"):
            self.assertEqual(self.request(report.url, host=host)[0], 404)
        self.assertEqual(self.request(report.url, host=f"localhost:{port}")[0], 200)
        self.assertEqual(self.request(report.url, method="POST")[0], 501)

    def test_random_route_and_port(self):
        first = browser.start_report("first", ttl_seconds=3)
        second = browser.start_report("second", ttl_seconds=3)
        self.assertNotEqual(urlsplit(first.url).path, urlsplit(second.url).path)
        self.assertNotEqual(urlsplit(first.url).port, urlsplit(second.url).port)
        self.assertRegex(urlsplit(first.url).path, r"^/[A-Za-z0-9_-]{32}$")

    def test_default_opener_is_optional_and_never_claims_rendering(self):
        for result in ((True, True), (True, False), (False, False)):
            with mock.patch.object(browser, "_open_default", return_value=result) as opener:
                report = browser.start_report("report", open_default=True, ttl_seconds=3)
            opener.assert_called_once_with(report.url)
            self.assertEqual(report.default_browser_attempted, result[0])
            self.assertEqual(report.default_browser_opened, result[1])

    def test_linux_native_opener_ignores_terminal_browser_and_bounds_wait(self):
        for result in (subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1), OSError("missing launcher"), subprocess.TimeoutExpired("launcher", 3)):
            with mock.patch.object(browser.sys, "platform", "linux"), mock.patch.dict(browser.os.environ, {"DISPLAY": ":1", "BROWSER": "lynx"}), mock.patch.object(browser.shutil, "which", return_value="/usr/bin/xdg-open"), mock.patch.object(browser.subprocess, "run", side_effect=result if isinstance(result, Exception) else None, return_value=result) as run:
                self.assertEqual(browser._open_default("http://127.0.0.1:1/token"),
                                 (True, isinstance(result, subprocess.CompletedProcess) and result.returncode == 0))
            self.assertEqual(run.call_args.args[0], ["/usr/bin/xdg-open", "http://127.0.0.1:1/token"])
            self.assertEqual(run.call_args.kwargs["timeout"], 3)
            self.assertNotIn("BROWSER", run.call_args.kwargs["env"])

    def test_headless_and_missing_launcher_skip_attempt(self):
        with mock.patch.object(browser.sys, "platform", "linux"), mock.patch.dict(browser.os.environ, {}, clear=True), mock.patch.object(browser.subprocess, "run") as run:
            self.assertEqual(browser._open_default("url"), (False, False))
            run.assert_not_called()
        with mock.patch.object(browser.sys, "platform", "linux"), mock.patch.dict(browser.os.environ, {"WAYLAND_DISPLAY": "wayland-1"}), mock.patch.object(browser.shutil, "which", return_value=None), mock.patch.object(browser.subprocess, "run") as run:
            self.assertEqual(browser._open_default("url"), (False, False))
            run.assert_not_called()

    def test_macos_native_opener(self):
        with mock.patch.object(browser.sys, "platform", "darwin"), mock.patch.object(browser.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(browser._open_default("url"), (True, True))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "url"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_blocked_opener_is_killed_and_returns(self):
        real_run = subprocess.run

        def blocked_launcher(command, **kwargs):
            return real_run([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

        started = time.monotonic()
        with mock.patch.object(browser.sys, "platform", "linux"), mock.patch.dict(browser.os.environ, {"DISPLAY": ":1"}), mock.patch.object(browser.shutil, "which", return_value="/usr/bin/xdg-open"), mock.patch.object(browser.subprocess, "run", side_effect=blocked_launcher):
            self.assertEqual(browser._open_default("url"), (True, False))
        self.assertLess(time.monotonic() - started, 4)
        self.assertIsNotNone(self.children[-1].poll())

    def test_ttl_exits_even_with_incomplete_http_request(self):
        report = browser.start_report("report", ttl_seconds=0.6)
        parsed = urlsplit(report.url)
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2) as connection:
            connection.sendall(b"GET / HTTP/1.1\r\nHost:")
            self.children[-1].wait(timeout=2)
        self.assertIsNotNone(self.children[-1].returncode)
        with self.assertRaises(OSError):
            socket.create_connection((parsed.hostname, parsed.port), timeout=0.2)

    def test_startup_failure_terminates_child(self):
        with self.assertRaisesRegex(RuntimeError, "could not start"):
            browser.start_report("report", startup_timeout=0.000001)
        self.assertIsNotNone(self.children[-1].poll())

    def test_worker_survives_caller_exit_then_expires(self):
        code = (
            "import json, sys; sys.path.insert(0, sys.argv[1]); "
            "from router_browser import start_report; "
            "report = start_report('after caller exit', ttl_seconds=1.2); "
            "print(json.dumps({'url': report.url, 'expires_at': report.expires_at}))"
        )
        caller = subprocess.run([sys.executable, "-c", code, str(Path(browser.__file__).parent)],
                                capture_output=True, text=True, check=True, timeout=3)
        report = json.loads(caller.stdout)
        self.assertEqual(self.request(report["url"])[2], b"after caller exit")
        time.sleep(max(0, report["expires_at"] - time.time()) + 0.1)
        with self.assertRaises(OSError):
            self.request(report["url"])

    def test_size_and_deadline_validation(self):
        for html in ("", b"bytes", "x" * (browser.MAX_HTML_BYTES + 1)):
            with self.assertRaises(ValueError):
                browser.start_report(html)
        for ttl in (0, -1, 601, True, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                browser.start_report("report", ttl_seconds=ttl)
        self.assertEqual(self.children, [])

    def test_large_payload_transferred_without_pipe_deadlock(self):
        html = "<p>" + "x" * 200000 + "</p>"
        report = browser.start_report(html, ttl_seconds=3)
        self.assertEqual(self.request(report.url)[2], html.encode())


if __name__ == "__main__":
    unittest.main()
