"""Short-lived, loopback-only report delivery without writing HTML to disk."""
import argparse
from dataclasses import dataclass
import http.server
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time


MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_TTL_SECONDS = 600
OPEN_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class BrowserReport:
    url: str
    expires_at: float
    default_browser_attempted: bool = False
    default_browser_opened: bool = False


def _bounded_seconds(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError("report timeout outside allowed range")
    return float(value)


def _stop(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _open_default(url):
    """Bound the native launcher; acknowledgement is not rendering evidence."""
    if sys.platform == "darwin":
        launcher = "/usr/bin/open"
    elif sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False, False
        launcher = shutil.which("xdg-open")
    else:
        launcher = None
    if not launcher:
        return False, False
    # Do not inherit an ambient terminal-browser command such as BROWSER=lynx.
    environment = dict(os.environ)
    environment.pop("BROWSER", None)
    try:
        result = subprocess.run([launcher, url], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=OPEN_TIMEOUT_SECONDS, env=environment,
                                start_new_session=True, check=False)
        return True, result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True, False


def start_report(html, *, open_default=False, ttl_seconds=MAX_TTL_SECONDS, startup_timeout=5):
    """Return a ready URL for the agent browser; optionally ask the OS browser.

    The browser boolean acknowledges only the opener, never a rendered page.
    The independent worker exits within ten minutes even if its caller exits.
    """
    ttl = _bounded_seconds(ttl_seconds, MAX_TTL_SECONDS)
    timeout = _bounded_seconds(startup_timeout, 30)
    if not isinstance(html, str):
        raise ValueError("report must be HTML text")
    payload = html.encode("utf-8")
    if not payload or len(payload) > MAX_HTML_BYTES:
        raise ValueError("report size outside allowed range")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve", "--ttl", str(ttl)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    deadline = time.monotonic() + timeout
    received, sent = b"", 0
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while b"\n" not in received:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("report server startup timed out")
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        sent += os.write(process.stdin.fileno(), payload[sent:sent + 65536])
                        if sent == len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk or len(received) + len(chunk) > 4096:
                            raise RuntimeError("report server did not become ready")
                        received += chunk
        ready = json.loads(received)
        if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+/[A-Za-z0-9_-]{32}", ready["url"]):
            raise ValueError("invalid report server address")
        report = BrowserReport(ready["url"], float(ready["expires_at"]))
    except Exception as exc:
        _stop(process)
        raise RuntimeError("could not start temporary report server") from exc
    finally:
        process.stdin.close()
        process.stdout.close()
    # Reap the child if this caller remains alive; the worker also has its own TTL.
    threading.Thread(target=process.wait, daemon=True).start()
    if open_default:
        attempted, opened = _open_default(report.url)
        report = BrowserReport(report.url, report.expires_at, attempted, opened)
    return report


def _serve(ttl):
    def expire(*_):
        raise SystemExit(0)

    # A hard deadline also bounds partial HTTP headers and blocked socket writes.
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, ttl)
    expires_at = time.time() + ttl
    document = sys.stdin.buffer.read(MAX_HTML_BYTES + 1)
    if not document or len(document) > MAX_HTML_BYTES:
        return 1
    route = "/" + secrets.token_urlsafe(24)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            hosts = self.headers.get_all("Host", [])
            status = 200 if len(hosts) == 1 and hosts[0] in allowed and self.path == route else 404
            body = document if status == 200 else b"Not found\n"
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if status == 200 else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with http.server.HTTPServer(("127.0.0.1", 0), Handler) as server:
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}{route}", "expires_at": expires_at}), flush=True)
        sys.stdout.close()
        server.serve_forever(poll_interval=0.1)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--ttl", type=float, default=MAX_TTL_SECONDS)
    args = parser.parse_args()
    raise SystemExit(_serve(_bounded_seconds(args.ttl, MAX_TTL_SECONDS)))
