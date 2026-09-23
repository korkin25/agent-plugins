#!/usr/bin/env python3
"""Подставная программа codex для тестов: `debug models` и `app-server` (JSON-RPC построчно).

Поведение и записи — в каталоге из переменной FAKE_CODEX_STATE:
calls.log — argv и pid каждого вызова; catalog.json — ответ debug models
(catalog.mode: fail | sleep | garbage | slow:<секунды>); app.json — сценарий app-server; app-requests.jsonl — сообщения.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def state_dir():
    return Path(os.environ["FAKE_CODEX_STATE"])


def debug_models(state):
    mode_file = state / "catalog.mode"
    mode = mode_file.read_text().strip() if mode_file.exists() else "ok"
    if mode.startswith("slow:"):  # как Codex, который тянет каталог по сети
        time.sleep(float(mode.split(":", 1)[1]))
        mode = "ok"
    if mode == "fail":
        print("error: cannot load models", file=sys.stderr)
        return 1
    if mode == "sleep":
        time.sleep(30)
        return 0
    if mode == "garbage":
        print("not json at all")
        return 0
    sys.stdout.write((state / "catalog.json").read_text(encoding="utf-8"))
    return 0


def app_server(state):
    """JSON построчно без поля jsonrpc, как app-server Codex 0.153–0.154: ошибки протокола — код -32600."""
    scenario_file = state / "app.json"
    scenario = json.loads(scenario_file.read_text(encoding="utf-8")) if scenario_file.exists() else {}
    replies = scenario.get("replies", {})
    log = state / "app-requests.jsonl"
    initialized = False

    def send(message):
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        message = json.loads(line)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(message, ensure_ascii=False) + "\n")
        method, request_id = message.get("method"), message.get("id")
        if method is None or request_id is None:
            continue
        if scenario.get("crash_on") == method:
            if scenario.get("exit_delay"):  # клиент видит EOF, а процесс ещё жив: гонка кода выхода
                sys.stdout.flush()
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
                time.sleep(scenario["exit_delay"])
            return 3
        if method not in KNOWN_METHODS and method not in replies:
            send({"error": {"code": -32600, "message": f"Invalid request: unknown variant `{method}`"},
                  "id": request_id})
            continue
        if method != "initialize" and not initialized:
            send({"error": {"code": -32600, "message": "Not initialized"}, "id": request_id})
            continue
        if scenario.get("noise"):
            send({"method": "configWarning", "params": {"summary": "noise", "details": None}, "emittedAtMs": 1})
            send({"id": 900, "method": "item/tool/requestUserInput", "params": {}})
        reply = replies.get(method, {"result": DEFAULT_RESULTS.get(method, {})})
        if "error" in reply:
            send({"error": reply["error"], "id": request_id})
        else:
            send({"id": request_id, "result": reply["result"]})
        if method == "initialize":
            initialized = True
    return 0


KNOWN_METHODS = ("initialize", "hooks/list", "config/batchWrite")
DEFAULT_RESULTS = {
    "initialize": {"userAgent": "fake-codex/0.154.0", "codexHome": "/nonexistent", "platformFamily": "unix",
                   "platformOs": "linux"},
    "hooks/list": {"data": []},
    "config/batchWrite": {"status": "ok", "version": "sha256:0", "filePath": "/nonexistent/config.toml",
                          "overriddenMetadata": None},
}


def main():
    state = state_dir()
    with open(state / "calls.log", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:], "pid": os.getpid()}) + "\n")
    args = sys.argv[1:]
    if args[:2] == ["debug", "models"]:
        return debug_models(state)
    if args[:1] == ["app-server"]:
        return app_server(state)
    print(f"fake codex: unsupported arguments {args}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
