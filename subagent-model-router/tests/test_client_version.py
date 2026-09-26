"""Synthetic process metadata and native-version transport; no live processes."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import router_client_version as version


class ClientVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="router-client-version-", dir=Path("/var/tmp").resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.cache = self.root / "private-cache"
        self.binary = self.root / "codex"
        self.binary.write_bytes(b"\x7fELFsynthetic executable metadata")
        self.binary.chmod(0o700)
        self.process(4242, 1, self.binary)
        self.event = dict(hook_event_name="SessionStart", session_id=str(uuid.uuid4()))
        self.parent = mock.patch.object(version.os, "getppid", return_value=4242)
        self.parent.start()
        self.addCleanup(self.parent.stop)

    def process(self, pid, parent, binary):
        folder = self.proc / str(pid)
        folder.mkdir(exist_ok=True)
        (folder / "stat").write_text(f"{pid} (process name) " + " ".join(["S", str(parent)] + ["0"] * 17 + ["987"]))
        (folder / "exe").symlink_to(binary)

    def initialize(self, agent="codex", event=None):
        return version.initialize_client_version(agent, event or self.event, proc_root=self.proc, state_root=self.cache)

    def resolve(self, agent="codex", event=None):
        return version.resolve_client_version(agent, event or self.event, state_root=self.cache)

    def path(self):
        return self.cache / version._slot(version._session_key("codex", self.event))

    def test_startup_probe_and_repeated_start_or_hooks_do_not_respawn(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0") as probe:
            self.assertEqual(self.initialize(), "0.157.0")
            self.assertEqual(self.initialize(), "0.157.0")
            with mock.patch.object(version, "_ancestor", side_effect=AssertionError("ordinary hook inspected processes")):
                for _ in range(5):
                    self.assertEqual(self.resolve(event=dict(self.event, hook_event_name="PreToolUse")), "0.157.0")
            probe.assert_called_once()

    def test_unknown_cache_miss_is_read_only(self):
        with mock.patch.object(version, "_ancestor", side_effect=AssertionError), mock.patch.object(version, "_probe", side_effect=AssertionError):
            self.assertIsNone(self.resolve())
        self.assertFalse(self.cache.exists())

    def test_only_session_start_initializes(self):
        with mock.patch.object(version, "_probe", side_effect=AssertionError):
            for name in ("UserPromptSubmit", "PreToolUse", "SessionEnd"):
                self.assertIsNone(self.initialize(event=dict(self.event, hook_event_name=name)))
        self.assertFalse(self.cache.exists())

    def test_config_missing_resume_invalidates_without_probe_or_creation(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        with mock.patch.object(version, "_ancestor", side_effect=AssertionError):
            version.invalidate_client_version("codex", self.event, state_root=self.cache)
        self.assertIsNone(self.resolve())
        missing = self.root / "missing"
        version.invalidate_client_version("codex", self.event, state_root=missing)
        self.assertFalse(missing.exists())

    def test_negative_startup_cached_without_repeat_probe(self):
        with mock.patch.object(version, "_probe", return_value=None) as probe:
            self.assertIsNone(self.initialize())
            self.assertIsNone(self.initialize())
            self.assertIsNone(self.resolve())
            probe.assert_called_once()

    def test_changed_executable_identity_requires_new_startup_probe(self):
        with mock.patch.object(version, "_probe", side_effect=["0.157.0", "0.158.0"]) as probe:
            self.initialize()
            old = self.binary.stat()
            os.utime(self.binary, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))
            self.assertEqual(self.initialize(), "0.158.0")
            self.assertEqual(probe.call_count, 2)

    def test_resumed_session_without_supported_ancestor_discards_old_version(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        with mock.patch.object(version, "_ancestor", return_value=None):
            self.assertIsNone(self.initialize())
        self.assertIsNone(self.resolve())

    def test_claude_native_version_filename_supported_and_helpers_rejected(self):
        native = self.root / "claude" / "versions" / "2.1.280"
        native.parent.mkdir(parents=True)
        self.binary.rename(native)
        (self.proc / "4242/exe").unlink()
        (self.proc / "4242/exe").symlink_to(native)
        with mock.patch.object(version, "_probe", return_value="2.1.280"):
            self.assertEqual(self.initialize("claude"), "2.1.280")
            self.assertIsNone(self.initialize("codex"))
        self.assertFalse(version._supported("/usr/bin/codex-helper", "codex"))
        self.assertFalse(version._supported("/usr/bin/claude-update", "claude"))

    def test_walks_bounded_ancestors_without_command_or_environment_reads(self):
        shell = self.root / "sh"
        shell.write_bytes(b"\x7fELF")
        self.process(4243, 4242, shell)
        with mock.patch.object(version.os, "getppid", return_value=4243), mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.assertEqual(self.initialize(), "0.157.0")
        (self.proc / "4243/stat").write_text("4243 (x) S 4243 " + " ".join(["0"] * 18))
        with mock.patch.object(version.os, "getppid", return_value=4243), mock.patch.object(version, "_probe", side_effect=AssertionError):
            self.assertIsNone(self.initialize())

    def test_unsafe_non_native_or_wrong_owner_executable_rejected(self):
        with mock.patch.object(version, "_probe", side_effect=AssertionError):
            self.binary.chmod(0o770)
            self.assertIsNone(self.initialize())
            self.binary.chmod(0o700)
            self.binary.write_bytes(b"#!/bin/sh")
            self.assertIsNone(self.initialize())
            with mock.patch.object(version.os, "geteuid", return_value=os.geteuid() + 1):
                self.assertIsNone(self.initialize())

    def test_exact_session_agent_and_nested_scope(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        self.assertIsNone(self.resolve("claude"))
        self.assertIsNone(self.resolve(event=dict(self.event, session_id=str(uuid.uuid4()))))
        self.assertIsNone(self.resolve(event=dict(self.event, agent_id="child")))
        self.assertIsNone(self.resolve(event=dict(self.event, session_id="bad")))
        self.assertEqual(self.resolve(event=dict(self.event, agent_id=None, turn_id=str(uuid.uuid4()))), "0.157.0")

    def test_concurrent_invalidation_never_returns_orphaned_cache(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        cached = version._cached
        def invalidate_after_read(fd, key):
            record = cached(fd, key)
            self.path().unlink()
            return record
        with mock.patch.object(version, "_cached", side_effect=invalidate_after_read):
            self.assertIsNone(self.resolve())

    def test_cache_private_bounded_metadata_only(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        raw = self.path().read_text()
        self.assertNotIn(str(self.binary), raw)
        self.assertNotIn(self.event["session_id"], raw)
        self.assertLessEqual(len(raw), version.MAX_RECORD)
        self.assertEqual(self.path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o700)
        with mock.patch.object(version, "MAX_SLOTS", 2), mock.patch.object(version, "_probe", return_value="0.157.0"):
            for _ in range(10):
                self.initialize(event=dict(self.event, session_id=str(uuid.uuid4())))
        self.assertLessEqual(len(list(self.cache.iterdir())), 3)

    def test_stale_corrupt_writable_symlink_and_locked_cache_unknown(self):
        with mock.patch.object(version, "_probe", return_value="0.157.0"):
            self.initialize()
        with mock.patch.object(version.time, "time", return_value=time.time() + version.CACHE_TTL + 1):
            self.assertIsNone(self.resolve())
        with self.path().open("rb") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIsNone(self.resolve())
        self.path().chmod(0o660)
        self.assertIsNone(self.resolve())
        self.path().chmod(0o600)
        self.path().write_text("{")
        self.assertIsNone(self.resolve())
        self.path().unlink()
        self.path().symlink_to(self.binary)
        self.assertIsNone(self.resolve())

    def fake_probe(self, data, agent="codex", returncode=0, silent=False):
        read_fd, write_fd = os.pipe()
        if not silent:
            os.write(write_fd, data)
            os.close(write_fd)
        output = os.fdopen(read_fd, "rb")
        child = mock.Mock(stdout=output, pid=999999, returncode=returncode)
        child.wait.return_value = returncode
        try:
            with mock.patch.object(version.subprocess, "Popen", return_value=child) as spawn, \
                    mock.patch.object(version.os, "killpg") as kill:
                found = version._probe(agent, 73)
            self.assertEqual(spawn.call_args.args[0], [agent, "--version"])
            self.assertEqual(spawn.call_args.kwargs["executable"], "/proc/self/fd/73")
            self.assertEqual(spawn.call_args.kwargs["pass_fds"], (73,))
            kill.assert_called_once()
            self.assertTrue(output.closed)
            return found
        finally:
            if silent:
                os.close(write_fd)
            output.close()

    def test_probe_exact_output_grammar_fd_dispatch_and_cleanup(self):
        self.assertEqual(self.fake_probe(b"codex-cli 0.157.0\n"), "0.157.0")
        self.assertEqual(self.fake_probe(b"2.1.280 (Claude Code)\n", "claude"), "2.1.280")
        self.assertIsNone(self.fake_probe(b"0.157.0\n"))
        self.assertIsNone(self.fake_probe(b"codex-cli 0.157.0\nnoise"))
        self.assertIsNone(self.fake_probe(b"codex-cli 0.157.0\n", returncode=1))

    def test_probe_output_and_deadline_bounded(self):
        self.assertIsNone(self.fake_probe(b"x" * (version.MAX_OUTPUT + 1)))
        with mock.patch.object(version, "PROBE_TIMEOUT", .03):
            started = time.monotonic()
            self.assertIsNone(self.fake_probe(b"", silent=True))
            self.assertLess(time.monotonic() - started, 1)


if __name__ == "__main__":
    unittest.main()
