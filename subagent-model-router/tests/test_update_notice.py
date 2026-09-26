"""Offline installed-version notices: only synthetic homes and fake CLI data."""
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import router_update_notice as notice


class UpdateNoticeTests(unittest.TestCase):
    def setUp(self):
        # Match secure-state fixtures: ignore unsafe TMPDIR and macOS /var symlinks.
        self.temp = tempfile.TemporaryDirectory(prefix="smr-notice-",
                                                dir=Path("/var/tmp").resolve())
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "CODEX_HOME": str(self.home / ".codex")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = self.home / ".config/subagent-model-router"
        self.config.mkdir(parents=True, mode=0o700)
        self.roots = {}
        for client in ("claude", "codex"):
            root = self.home / f".{client}/plugins/cache/korkin25/subagent-model-router/0.4.8"
            root.mkdir(parents=True)
            self.roots[client] = root
        for path in self.home.rglob("*"):
            if path.is_dir():
                path.chmod(0o700 if path == self.config else 0o755)
        self.event = {"hook_event_name": "UserPromptSubmit", "session_id": str(uuid.uuid4()),
                      "cwd": str(self.home / "project"), "prompt": "NEVER-PERSIST-THIS"}
        self.registry = self.home / ".claude/plugins/installed_plugins.json"
        self.write_registry()
        self.fake = self.home / "fake-codex"
        self.calls = self.home / "calls"
        self.payload = self.home / "payload.json"
        self.payload.write_text(json.dumps(self.codex_data()))
        self.fake.write_text(f'#!{sys.executable}\nimport pathlib,sys\n'
            f'assert sys.argv[1:] == ["plugin", "list", "--marketplace", "korkin25", "--json"]\n'
            f'with open({str(self.calls)!r}, "a") as f: f.write("call\\n")\n'
            f'print(pathlib.Path({str(self.payload)!r}).read_text())\n')
        self.fake.chmod(0o700)

    def codex_data(self, version="0.4.9", **kwargs):
        item = dict(pluginId=notice.PLUGIN_ID, name="subagent-model-router", version=version,
                    installed=True, enabled=True)
        item.update(kwargs)
        return {"installed": [item]}

    def write_registry(self, version="0.4.9", entries=None):
        install = self.roots["claude"].parent / version
        install.mkdir(exist_ok=True)
        if entries is None:
            entries = [dict(scope="user", version=version, installPath=str(install))]
        self.registry.write_text(json.dumps({"version": 2, "plugins": {notice.PLUGIN_ID: entries}}))
        self.registry.chmod(0o644)

    def run_notice(self, client="claude", **kwargs):
        values = dict(event=self.event, plugin_root=self.roots[client], running_version="0.4.8",
                      config_dir=self.config, codex_binary=str(self.fake))
        values.update(kwargs)
        return notice.update_notice(**values)

    def fresh_event(self):
        directory = self.config / "update-notice"
        occupied = {p.name for p in directory.glob("*.json")} if directory.exists() else set()
        while True:
            session = str(uuid.uuid4())
            key = hashlib.sha256(f"claude/{session}".encode()).hexdigest()
            if f"{int(key[:8], 16) % notice.MAX_SLOTS:03d}.json" not in occupied:
                return dict(self.event, session_id=session)

    def expire_cache(self):
        for path in (self.config / "update-notice").glob("*.json"):
            state = json.loads(path.read_text())
            state["checked"] -= notice.CACHE_SECONDS + 1
            path.write_text(json.dumps(state))

    def test_newer_once_per_session_and_version(self):
        first = self.run_notice()
        self.assertEqual(set(first), {"systemMessage"})
        self.assertIn("установлен 0.4.9", first["systemMessage"])
        self.assertIn("из 0.4.8", first["systemMessage"])
        self.assertIn("/reload-plugins", first["systemMessage"])
        self.assertNotIn("--force", first["systemMessage"])
        self.assertEqual(self.run_notice(), {})
        self.write_registry("0.5.0")
        self.assertEqual(self.run_notice(), {})
        self.expire_cache()
        self.assertIn("0.5.0", self.run_notice()["systemMessage"])
        self.write_registry("0.4.9")
        self.expire_cache()
        self.assertEqual(self.run_notice(), {})
        other = self.fresh_event()
        self.assertTrue(self.run_notice(event=other))

    def test_equal_older_invalid_and_missing_are_silent(self):
        for version in ("0.4.8", "0.4.7", "garbage", "0.04.9", "1.0.0-beta"):
            with self.subTest(version=version):
                self.write_registry(version)
                self.assertEqual(self.run_notice(event=self.fresh_event()), {})
        self.registry.unlink()
        self.assertEqual(self.run_notice(), {})

    def test_unknown_root_and_invalid_event_do_not_create_state(self):
        self.assertEqual(self.run_notice(plugin_root=self.home), {})
        for event in ({}, dict(self.event, session_id="not-uuid"), dict(self.event, hook_event_name="PreToolUse"),
                      dict(self.event, agent_id="subagent")):
            self.assertEqual(self.run_notice(event=event), {})
        self.assertFalse((self.config / "update-notice").exists())

    def test_codex_cli_and_cached_failures(self):
        self.assertIn("Начните новую сессию Codex", self.run_notice("codex")["systemMessage"])
        self.assertEqual(self.run_notice("codex"), {})
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.expire_cache()
        self.payload.write_text("invalid JSON")
        self.assertEqual(self.run_notice("codex"), {})
        self.assertEqual(self.run_notice("codex"), {})
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)

    def test_native_codex_root_prompt_with_turn_id_notifies(self):
        # Codex hooks/src/schema.rs UserPromptSubmitCommandInput serializes
        # turn_id for every prompt; absent agent_id is the native root shape.
        event = dict(self.event, turn_id="turn-1", transcript_path=None,
                     model="gpt-6", permission_mode="default")
        self.assertTrue(self.run_notice("codex", event=event))
        # Older adapters may serialize the same optional fields as JSON null.
        event.update(agent_id=None, agent_type=None, turn_id="turn-2")
        self.assertEqual(self.run_notice("codex", event=event), {})
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(notice._session(event), self.event["session_id"])

    def test_native_codex_subagent_prompt_does_not_inspect_installation(self):
        # SubagentCommandInputFields copies the actual subagent context ID.
        event = dict(self.event, turn_id="turn-1", transcript_path=None,
                     model="gpt-6", permission_mode="default",
                     agent_id=str(uuid.uuid4()), agent_type="worker")
        self.assertEqual(self.run_notice("codex", event=event), {})
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.config / "update-notice").exists())

    def test_codex_rejects_uninstalled_disabled_ambiguous_and_available_only(self):
        variants = [self.codex_data(installed=False), self.codex_data(enabled=False),
                    self.codex_data(pluginId="subagent-model-router@other"), {"available": self.codex_data()["installed"]},
                    {"installed": self.codex_data()["installed"] * 2}]
        for payload in variants:
            with self.subTest(payload=payload):
                self.payload.write_text(json.dumps(payload))
                self.assertEqual(self.run_notice("codex", event=self.fresh_event()), {})

    def test_cli_timeout_and_output_bound(self):
        for code, budget, overflow in (("import time; time.sleep(10)", .05, False),
                                       ("print('x' * 300000)", 30, True)):
            with self.subTest(overflow=overflow):
                self.fake.write_text(f"#!{sys.executable}\n{code}\n")
                processes, chunks = [], []
                popen, read = notice.subprocess.Popen, notice.os.read

                def observe_process(*args, **kwargs):
                    process = popen(*args, **kwargs)
                    wait = process.wait
                    self.addCleanup(wait)
                    self.addCleanup(process.stdout.close)

                    def delayed_reap(*args, **kwargs):
                        if kwargs.get('timeout') == .1:
                            raise notice.subprocess.TimeoutExpired(process.args, .1)
                        return wait(*args, **kwargs)

                    process.wait = mock.Mock(side_effect=delayed_reap)
                    processes.append(process)
                    return process

                def observe_read(*args):
                    chunk = read(*args)
                    chunks.append(chunk)
                    return chunk

                with notice.selectors.DefaultSelector() as selector:
                    with mock.patch.object(notice, 'CLI_TIMEOUT', budget), \
                            mock.patch.object(notice.subprocess, 'Popen', side_effect=observe_process), \
                            mock.patch.object(notice.os, 'read', side_effect=observe_read), \
                            mock.patch.object(notice.selectors, 'DefaultSelector', return_value=selector), \
                            mock.patch.object(selector, 'select', wraps=selector.select) as select:
                        self.assertEqual(self.run_notice('codex', event=self.fresh_event()), {})
                for call in select.call_args_list:
                    self.assertGreater(call.args[0], 0)
                    self.assertLessEqual(call.args[0], budget)
                if overflow:
                    self.assertGreater(len(b''.join(chunks)), notice.MAX_INPUT_BYTES)
                [process] = processes
                self.assertIsNotNone(process.returncode)
                self.assertTrue(process.stdout.closed)
                with self.assertRaises(ChildProcessError):
                    os.waitpid(process.pid, os.WNOHANG)

    def test_scope_and_install_path_must_be_unambiguous(self):
        entry = json.loads(self.registry.read_text())["plugins"][notice.PLUGIN_ID][0]
        project = dict(entry, scope="project", projectPath=self.event["cwd"])
        self.write_registry(entries=[entry, project])
        self.assertEqual(self.run_notice(), {})
        self.write_registry(entries=[project])
        self.expire_cache()
        self.assertTrue(self.run_notice())
        for change in ({"installPath": str(self.home)}, {"scope": "managed"}, {"version": "0.9.0"}):
            self.write_registry(entries=[dict(entry, **change)])
            self.assertEqual(self.run_notice(event=self.fresh_event()), {})

    def test_security_and_private_bounded_storage(self):
        self.assertTrue(self.run_notice())
        directory = self.config / "update-notice"
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        files = list(directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        raw = files[0].read_text()
        for forbidden in (self.event["session_id"], self.event["prompt"], str(self.home)):
            self.assertNotIn(forbidden, raw)
        self.assertLess(len(raw), notice.MAX_BYTES)
        self.config.chmod(0o770)
        self.assertEqual(self.run_notice(event=self.fresh_event()), {})

    def test_symlink_and_unsafe_slot_are_silent(self):
        directory = self.config / "update-notice"
        directory.symlink_to(self.home, target_is_directory=True)
        self.assertEqual(self.run_notice(), {})
        directory.unlink()
        self.assertTrue(self.run_notice())
        path = next(directory.iterdir())
        path.chmod(0o644)
        self.assertEqual(self.run_notice(), {})

    def test_nonblocking_lock_and_race_emit_once(self):
        directory = self.config / "update-notice"
        directory.mkdir(mode=0o700)
        key = hashlib.sha256(f'claude/{self.event["session_id"]}'.encode()).hexdigest()
        slot = directory / f"{int(key[:8], 16) % notice.MAX_SLOTS:03d}.json"
        fd = os.open(slot, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_notice(), {})
        finally:
            os.close(fd)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.run_notice(), range(16)))
        self.assertEqual(sum(bool(result) for result in results), 1)

    def test_collisions_fail_closed_and_expired_slots_reusable(self):
        self.assertTrue(self.run_notice())
        path = next((self.config / "update-notice").iterdir())
        target = int(path.stem)
        for _ in range(10000):
            session = str(uuid.uuid4())
            digest = hashlib.sha256(f"claude/{session}".encode()).hexdigest()
            if int(digest[:8], 16) % notice.MAX_SLOTS == target:
                break
        else:
            self.fail("No synthetic slot collision found")
        other = dict(self.event, session_id=session)
        self.assertEqual(self.run_notice(event=other), {})
        state = json.loads(path.read_text())
        state["touched"] -= notice.TTL_SECONDS + 1
        path.write_text(json.dumps(state))
        self.assertTrue(self.run_notice(event=other))
        self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_environment_config_locations_and_absent_other_client(self):
        import shutil
        shutil.rmtree(self.home / ".codex")
        self.assertTrue(self.run_notice())
        custom = self.home / "alternate-claude"
        (self.home / ".claude").rename(custom)
        root = custom / "plugins/cache/korkin25/subagent-model-router/0.4.8"
        install = root.parent / "0.4.9"
        (custom / "plugins/installed_plugins.json").write_text(json.dumps({"plugins": {notice.PLUGIN_ID:
            [dict(scope="user", version="0.4.9", installPath=str(install))]}}))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom)}):
            self.assertTrue(self.run_notice(plugin_root=root, event=self.fresh_event()))


if __name__ == "__main__":
    unittest.main()
