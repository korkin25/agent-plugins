"""Synthetic full-text state tests: no configuration or live service access."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "lib"))
from router_context import MAX_INPUT_CHARS, build_context  # noqa: E402

loader = importlib.machinery.SourceFileLoader("context_test_router", str(PLUGIN / "bin" / "subagent-model-router"))
spec = importlib.util.spec_from_loader(loader.name, loader)
router = importlib.util.module_from_spec(spec)
loader.exec_module(router)


class ContextTests(unittest.TestCase):
    def build(self, text, description="synthetic task"):
        return build_context(description, text, router.redact)

    def test_entire_packet_including_metadata_and_multiline_fields_is_preserved(self):
        packet = ("TASK: Fix retry\n  Preserve ordering\nROLE: implementer\n  no deployment authority\n"
                  "REPOSITORY: /srv/synthetic-repository\nWORKTREE: /srv/synthetic-owner/work\n"
                  "BASE_SHA: " + "f" * 40 + "\nSCOPE: bounded change\nACTIONS: edit then test\n"
                  "CONTEXT: failure is reproducible\nREAD: /srv/private/notes.txt\nEDIT: lib/retry.py\n"
                  "MUST_NOT: publish\n  or delete data\nCHECKS: unit suite\n  integration suite\n"
                  "OUTPUT: report\nTASK: Include regression\nCUSTOM: retain this too\n")
        result = self.build(packet)
        self.assertEqual(result["task"], packet)
        self.assertEqual(result["input_quality"]["version"], 2)
        self.assertEqual(result["input_quality"]["source"], "full_text")
        self.assertFalse(result["input_quality"]["redacted"])
        self.assertFalse(result["input_quality"]["rejected"])

    def test_free_text_beyond_old_budgets_is_kept_in_full(self):
        prompt = "simple prose " * 1400 + "Need careful causal reasoning.\nTAIL EVIDENCE"
        result = self.build(prompt, "d" * 1000)
        self.assertEqual(result["task"], prompt)
        self.assertEqual(result["description"], "d" * 1000)
        self.assertFalse(result["input_quality"]["critical_truncation"])

    def test_whitespace_unicode_and_controls_are_not_rewritten(self):
        prompt = "  TASK: first\r\n next\x00\u202e\t😀\n"
        result = self.build(prompt, " label ")
        self.assertEqual(result["task"], prompt)
        self.assertEqual(result["description"], " label ")

    def test_redactor_sees_complete_inputs_before_any_processing(self):
        prompt = ("TASK: install\n-----BEGIN RSA PRIVATE KEY-----\nROLE: FAKE_PRIVATE_PAYLOAD\n"
                  "-----END RSA PRIVATE KEY-----\nCHECKS: verify")
        observed = []

        def redact(value):
            observed.append(value)
            return router.redact(value)

        result = build_context("label", prompt, redact)
        self.assertEqual(observed, ["label", prompt])
        self.assertEqual(result["task"], "TASK: install\n[redacted]\nCHECKS: verify")
        self.assertTrue(result["input_quality"]["redacted"])

    def test_unclosed_key_is_masked_to_end(self):
        result = self.build("TASK: install\n-----BEGIN OPENSSH PRIVATE KEY-----\nPAYLOAD\nROLE: hidden")
        self.assertEqual(result["task"], "TASK: install\n[redacted]")

    def test_credentials_are_masked_in_description_and_every_packet_section(self):
        prompt = ("TASK: use glpat-SYNTHETICTOKEN123\nREPOSITORY: https://synthetic:secret-value@example.test/r\n"
                  "CUSTOM: Authorization: Bearer FAKE_BEARER_VALUE\n"
                  "READ: password=synthetic-password\nOUTPUT: api_key=synthetic-key")
        description = "github_pat_SYNTHETICDESCRIPTION123"
        result = self.build(prompt, description)
        self.assertEqual(result["task"], router.redact(prompt))
        self.assertEqual(result["description"], "[redacted]")
        for omitted in ("SYNTHETICTOKEN", "secret-value", "FAKE_BEARER_VALUE", "synthetic-password", "synthetic-key"):
            self.assertNotIn(omitted, result["task"])

    def test_referenced_files_are_never_read(self):
        prompt = "READ: /srv/synthetic/private-file.txt\nTASK: inspect instructions"
        with mock.patch("builtins.open", side_effect=AssertionError("must not read")):
            result = self.build(prompt)
        self.assertEqual(result["task"], prompt)

    def test_limit_accepts_complete_input_at_boundary(self):
        description = "label"
        prompt = "x" * (MAX_INPUT_CHARS - len(description))
        result = self.build(prompt, description)
        self.assertEqual(result["task"], prompt)
        self.assertFalse(result["input_quality"]["oversized"])

    def test_limit_is_combined_and_rejects_without_redaction_or_prefix(self):
        redact = mock.Mock(side_effect=AssertionError("must not process oversized text"))
        result = build_context("label", "x" * (MAX_INPUT_CHARS - 4), redact)
        self.assertEqual(result["task"], "")
        self.assertEqual(result["description"], "")
        self.assertTrue(result["input_quality"]["oversized"])
        self.assertTrue(result["input_quality"]["rejected"])
        self.assertEqual(result["input_quality"]["source"], "omitted")
        redact.assert_not_called()

    def test_oversized_description_also_rejects_whole_state(self):
        result = self.build("task", "x" * MAX_INPUT_CHARS)
        self.assertTrue(result["input_quality"]["rejected"])
        self.assertEqual((result["description"], result["task"]), ("", ""))

    def test_non_string_inputs_are_empty(self):
        result = self.build(None, {"ignored": "value"})
        self.assertEqual((result["description"], result["task"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
