#!/usr/bin/env python3
"""Подставной сервер Jev: http.server в потоке, ответы по сценарию, запись запросов.

Отдельно (сквозная проверка): fake_jev.py --scenario light --record FILE --port-file FILE.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def jev_body(light, standard, heavy, risky, review, model="jev-1.13.0", **extra):
    """Ответ в форме TypeSafe (extra — поля OpenRouter: id, provider)."""
    tier = {"light": light, "standard": standard, "heavy": heavy}
    body = {
        "model": model,
        "answers": {
            "tier": {"type": "choice", "choice": max(tier, key=tier.get), "probabilities": tier,
                     "confidence": 0.8},
            "risky": {"type": "noul", "noul": risky},
            "review": {"type": "noul", "noul": review},
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }
    body.update(extra)
    return body


SCENARIOS = {
    "light": jev_body(0.90, 0.08, 0.02, 0.05, 0.02),
    "standard": jev_body(0.30, 0.60, 0.10, 0.10, 0.10),
    "heavy": jev_body(0.05, 0.15, 0.80, 0.10, 0.10),
    "uncertain": jev_body(0.45, 0.20, 0.35, 0.10, 0.10),
    "risky": jev_body(0.90, 0.08, 0.02, 0.60, 0.02),
    "review": jev_body(0.90, 0.08, 0.02, 0.05, 0.80),
}


class Reply:
    """Реплика: delay — пауза до ответа; trickle — пауза между байтами тела."""

    def __init__(self, status=200, body=None, headers=None, delay=0.0, trickle=0.0):
        self.status = status
        if body is None:
            body = SCENARIOS["light"]
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = dict(headers or {})
        self.delay = delay
        self.trickle = trickle


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class FakeJev:
    """Отвечает репликами по порядку (последняя повторяется) и пишет запросы в список и файл."""

    def __init__(self, replies=None, record_path=None):
        self.replies = list(replies or [Reply()])
        self.requests = []
        self.record_path = record_path
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                owner._record(self.command, self.path, self.headers, body)
                reply = owner._next()
                if reply.delay:
                    time.sleep(reply.delay)
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(reply.body)))
                    for name, value in reply.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    if not reply.trickle:
                        self.wfile.write(reply.body)
                        return
                    for index in range(len(reply.body)):
                        self.wfile.write(reply.body[index:index + 1])
                        self.wfile.flush()
                        time.sleep(reply.trickle)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_POST = do_GET = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_any

            def log_message(self, *args):
                pass

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _record(self, method, path, headers, body):
        entry = {"method": method, "path": path, "headers": dict(headers.items()),
                 "body": body.decode("utf-8", errors="replace")}
        with self._lock:
            self.requests.append(entry)
            if self.record_path:
                with open(self.record_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _next(self):
        with self._lock:
            return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Подставной сервер Jev для сквозной проверки.")
    parser.add_argument("--scenario", default="light", choices=sorted(SCENARIOS))
    parser.add_argument("--record", required=True, help="файл JSONL с запросами")
    parser.add_argument("--port-file", required=True, help="куда записать порт")
    args = parser.parse_args()
    fake = FakeJev([Reply(body=SCENARIOS[args.scenario], headers={"x-typesafe-request-id": "fake-e2e"})],
                   record_path=args.record)
    with open(args.port_file, "w", encoding="utf-8") as fh:
        fh.write(str(fake.server.server_address[1]))
    fake.server.serve_forever()


if __name__ == "__main__":
    main()
