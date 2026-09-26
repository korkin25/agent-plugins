#!/usr/bin/env python3
"""Synthetic native Claude SDK initialize; never contacts a service."""
import json
import os
from pathlib import Path
import sys
import time

MODELS = [
    {"value": "haiku", "resolvedModel": "claude-haiku-4-5", "description": "Synthetic Haiku: fast scoped tasks"},
    {"value": "sonnet", "resolvedModel": "claude-sonnet-5", "description": "Synthetic Sonnet: routine engineering",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "opus[1m]", "resolvedModel": "claude-opus-5-5[1m]", "description": "Synthetic Opus: everyday and complex tasks",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "claude-fable-5-1", "resolvedModel": "claude-fable-5-1", "description": "Synthetic Fable: hardest and long-running tasks",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
]


def main():
    state = Path(os.environ["FAKE_CLAUDE_STATE"])
    line = sys.stdin.readline()
    observed = {"argv": sys.argv[1:], "pid": os.getpid(), "cwd": os.getcwd(),
                "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"), "home": os.environ.get("HOME"),
                "config_mode": os.stat(os.environ["CLAUDE_CONFIG_DIR"]).st_mode & 0o777,
                "environment_keys": sorted(os.environ), "request": json.loads(line)}
    with (state / "calls.log").open("a") as stream:
        stream.write(json.dumps(observed) + "\n")
    mode_file = state / "mode"
    mode = mode_file.read_text().strip() if mode_file.exists() else "ok"
    if mode.startswith("slow:"):
        time.sleep(float(mode.partition(":")[2]))
    if mode == "sleep":
        time.sleep(60)
    if mode == "huge":
        sys.stdout.write("x" * (3 * 1024 * 1024))
        sys.stdout.flush()
        return 0
    if mode == "garbage":
        print("not JSON", flush=True)
        return 0
    models_file = state / "models.json"
    models = json.loads(models_file.read_text()) if models_file.exists() else MODELS
    response = {"type": "control_response", "response": {"subtype": "success",
                "request_id": observed["request"]["request_id"],
                "response": {"models": models, "account": {"secret": "SYNTHETIC_ACCOUNT_NOT_RETAINED"},
                             "commands": [{"name": "SYNTHETIC_COMMAND_NOT_RETAINED"}]}}}
    if mode == "error":
        response["response"]["subtype"] = "error"
    if mode == "wrong_id":
        response["response"]["request_id"] = "unrelated"
    print(json.dumps(response), flush=True)
    remaining = sys.stdin.read()
    if remaining:
        (state / "unexpected-input").write_text(remaining)
        return 7
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
