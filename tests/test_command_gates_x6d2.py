"""
X6-D2 tests: command_gates.py -- classification only, never execute.

Run: python tests/test_command_gates_x6d2.py

Gates 8-11 classify parsed command objects.  These tests verify conservative
classification, hard safety invariants, secret redaction, and that the gates
never execute anything, never spawn processes, and never call any API.
The fake key below is not a real credential.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import command_gates as cg
import command_parser as cp


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_GUARDRAILS = """\
## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""


def _cmd(body, scope="Limit changes to docs/ only."):
    return (f"# Next Claude Code Instruction\n\n{body}\n\n"
            f"## Scope\n{scope}\n\n{_GUARDRAILS}")


def _gate(body, scope="Limit changes to docs/ only."):
    return cg.evaluate_markdown(_cmd(body, scope))


_INVARIANT_FIXTURES = (
    _cmd("Update docs/STATUS.md with the latest test count."),
    _cmd("Run git push origin main."),
    _cmd("Read the .env file."),
    "just words with no structure",
    "",
)


# ---------------------------------------------------------------------------
# Classification (Gate 10) and pass/review/block behavior
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):

    def test_docs_only_passes_but_cannot_execute(self):
        r = _gate("Update docs/STATUS.md with the latest test count.")
        self.assertEqual(r["intent"], "docs_only")
        self.assertEqual(r["overall_status"], "passed_for_review")
        self.assertEqual(r["risk_level"], "low")
        for g in cg.ALL_GATES:
            self.assertIn(g, r["gates_passed"])
        self.assertFalse(r["can_execute"])
        self.assertFalse(r["x6_enabled"])
        self.assertTrue(r["requires_human_approval"])

    def test_tests_only_classified(self):
        r = _gate("Run tests/test_bridge_phase_d.py and confirm it passes.",
                  scope="Limit changes to tests/ only.")
        self.assertEqual(r["intent"], "tests_only")
        self.assertEqual(r["overall_status"], "passed_for_review")

    def test_safe_script_classified(self):
        r = _gate("Review the output of scripts/show-status.ps1.",
                  scope="Limit changes to scripts/ only.")
        self.assertEqual(r["intent"], "safe_script")
        self.assertEqual(r["overall_status"], "passed_for_review")

    def test_source_change_requires_review(self):
        r = _gate("Refactor src/module.py to simplify the parsing loop.",
                  scope="src/ only.")
        self.assertEqual(r["intent"], "source_change")
        self.assertEqual(r["overall_status"], "needs_review")
        self.assertEqual(r["risk_level"], "medium")
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_INTENT_CLASSIFIER, failed)

    def test_config_change_requires_review(self):
        r = _gate("Check config/bridge.config.json for the rate limit value.",
                  scope="config/ read only.")
        self.assertEqual(r["intent"], "config_change")
        self.assertEqual(r["overall_status"], "needs_review")

    def test_dependency_change_blocks(self):
        r = _gate("Then pip install requests before running the suite.")
        self.assertEqual(r["intent"], "dependency_change")
        self.assertEqual(r["overall_status"], "blocked")
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_DESTRUCTIVE, failed)

    def test_git_push_blocks(self):
        r = _gate("Run git push origin main to publish the change.")
        self.assertEqual(r["intent"], "git_operation")
        self.assertEqual(r["overall_status"], "blocked")
        self.assertTrue(r["blocked_reasons"])

    def test_destructive_command_blocks(self):
        r = _gate("Clean the workspace with rm -rf build/ first.")
        self.assertEqual(r["intent"], "destructive")
        self.assertEqual(r["overall_status"], "blocked")
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_DESTRUCTIVE, failed)

    def test_external_download_blocks(self):
        r = _gate("Download the dataset from https://example.com/data.zip.")
        self.assertEqual(r["intent"], "external_access")
        self.assertEqual(r["overall_status"], "blocked")

    def test_ambiguous_command_is_unclear_and_needs_review(self):
        r = _gate("Review the brief context and write a final status report.",
                  scope="Limit changes to the current project only.")
        self.assertEqual(r["intent"], "unclear")
        self.assertEqual(r["overall_status"], "needs_review")

    def test_guardrail_bullets_do_not_self_trigger(self):
        """The Forbidden section mentions push/execute language but a docs
        command must still pass."""
        r = _gate("Update docs/STATUS.md with the latest counts.")
        self.assertEqual(r["overall_status"], "passed_for_review")


# ---------------------------------------------------------------------------
# Gate 8: COMMAND_TARGET_ALLOWLIST
# ---------------------------------------------------------------------------

class TestGate8Allowlist(unittest.TestCase):

    def _blocked_with_gate8(self, body, scope="docs/ only."):
        r = _gate(body, scope=scope)
        self.assertEqual(r["overall_status"], "blocked", body)
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_TARGET_ALLOWLIST, failed)
        return r

    def test_env_path_blocks(self):
        self._blocked_with_gate8("Read the .env file for the settings.")

    def test_git_dir_blocks(self):
        self._blocked_with_gate8("Inspect .git/config for the remote URL.")

    def test_absolute_windows_path_blocks(self):
        self._blocked_with_gate8(r"Copy C:\Temp\notes.md into the docs folder.")

    def test_absolute_posix_path_blocks(self):
        self._blocked_with_gate8("Read /etc/passwd for the entries.")

    def test_parent_traversal_blocks(self):
        self._blocked_with_gate8("Review ../other-repo/file.md for context.")

    def test_tradingview_light_blocks(self):
        self._blocked_with_gate8("Open TradingView Light/chart.txt and check it.")

    def test_pinescript_agents_blocks(self):
        self._blocked_with_gate8("Update pinescript-agents/agent.md.")

    def test_secret_filename_blocks(self):
        self._blocked_with_gate8("Check docs/credentials.json for the values.")

    def test_outside_allowlist_is_review_not_block(self):
        r = _gate("Tidy the notes in notes/scratch.md.", scope="notes/ only.")
        self.assertEqual(r["overall_status"], "needs_review")
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_TARGET_ALLOWLIST, failed)
        self.assertFalse(r["blocked_reasons"])

    def test_root_markdown_is_allowed(self):
        r = _gate("Update README.md with the new test count.",
                  scope="Root markdown only.")
        self.assertIn(cg.GATE_TARGET_ALLOWLIST, r["gates_passed"])
        self.assertEqual(r["overall_status"], "passed_for_review")


# ---------------------------------------------------------------------------
# Gate 9: NO_SECRETS_GATE
# ---------------------------------------------------------------------------

class TestGate9Secrets(unittest.TestCase):

    def test_secret_content_blocks_and_redacts(self):
        text = _cmd(f"Use OPENAI_API_KEY={_FAKE_SECRET} for docs/ work.")
        r = cg.evaluate_markdown(text)
        self.assertEqual(r["overall_status"], "blocked")
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_NO_SECRETS, failed)
        serialized = json.dumps(r)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)

    def test_private_key_block(self):
        text = _cmd("Embed this:\n-----BEGIN RSA PRIVATE KEY-----\nabc")
        r = cg.evaluate_markdown(text)
        failed = [e["gate"] for e in r["gates_failed"]]
        self.assertIn(cg.GATE_NO_SECRETS, failed)

    def test_clean_command_passes_gate9(self):
        r = _gate("Update docs/STATUS.md with the latest counts.")
        self.assertIn(cg.GATE_NO_SECRETS, r["gates_passed"])


# ---------------------------------------------------------------------------
# Degraded parser output
# ---------------------------------------------------------------------------

class TestDegradedInput(unittest.TestCase):

    def test_malformed_command_never_passes(self):
        r = cg.evaluate_markdown("just some words with no headings")
        self.assertIn(r["overall_status"], ("needs_review", "blocked"))
        self.assertNotEqual(r["overall_status"], "passed_for_review")

    def test_empty_command_blocks(self):
        r = cg.evaluate_markdown("")
        self.assertEqual(r["overall_status"], "blocked")
        self.assertTrue(any("not evaluable" in b for b in r["blocked_reasons"]))

    def test_missing_file_parser_result_blocks(self):
        parsed = cp.parse_command_file(Path(tempfile.gettempdir()) /
                                       "definitely-not-here-x6d2.md")
        r = cg.evaluate_command(parsed)
        self.assertEqual(r["overall_status"], "blocked")

    def test_needs_review_parser_result_never_passes(self):
        """Even a harmless body cannot pass when the parser flagged it."""
        r = cg.evaluate_markdown("no title here, just docs/notes.md mention")
        self.assertNotEqual(r["overall_status"], "passed_for_review")


# ---------------------------------------------------------------------------
# Hard safety invariants
# ---------------------------------------------------------------------------

class TestInvariants(unittest.TestCase):

    def test_invariants_hold_for_every_fixture(self):
        for text in _INVARIANT_FIXTURES:
            r = cg.evaluate_markdown(text)
            self.assertFalse(r["x6_enabled"], "x6_enabled must stay False")
            self.assertFalse(r["can_execute"], "can_execute must stay False")
            self.assertTrue(r["classification_only"])
            self.assertTrue(r["requires_human_approval"])

    def test_invariants_hold_for_missing_file(self):
        r = cg.evaluate_command({"parse_status": "missing_file"})
        self.assertFalse(r["x6_enabled"])
        self.assertFalse(r["can_execute"])
        self.assertTrue(r["classification_only"])
        self.assertTrue(r["requires_human_approval"])


# ---------------------------------------------------------------------------
# Safety: never executes, never calls out
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_gates_never_call_subprocess_or_system(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system:
            for text in _INVARIANT_FIXTURES:
                cg.evaluate_markdown(text)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()

    def test_gates_never_open_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            cg.evaluate_markdown(
                _cmd("Download the dataset from https://example.com/x.zip."))
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        source = Path(cg.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "import urllib",
                       "openai_planner", "import claude_runner",
                       "import bridge", "import auto_exchange",
                       "import requests"):
            self.assertNotIn(needle, source,
                             f"gates source must not contain {needle!r}")

    def test_runtime_modules_do_not_import_gates(self):
        """X6-D2 is connected to nothing: no runtime module imports it."""
        for name in ("bridge.py", "claude_runner.py", "auto_exchange.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("command_gates", source,
                             f"{name} must not import command_gates")
            self.assertNotIn("command_parser", source,
                             f"{name} must not import command_parser")


# ---------------------------------------------------------------------------
# Read-only CLI
# ---------------------------------------------------------------------------

class TestCli(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cg.main(argv)
        return rc, buf.getvalue()

    def test_cli_gates_file_and_prints_json(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Update docs/STATUS.md with the latest counts."),
                     encoding="utf-8")
        rc, out = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["intent"], "docs_only")
        self.assertEqual(parsed["overall_status"], "passed_for_review")
        self.assertFalse(parsed["can_execute"])

    def test_cli_missing_file_fails_safely(self):
        rc, out = self._run_cli(["--input", str(self.tmp / "nope.md")])
        self.assertEqual(rc, 1)
        parsed = json.loads(out)
        self.assertEqual(parsed["overall_status"], "blocked")
        self.assertFalse(parsed["can_execute"])

    def test_cli_does_not_modify_input_file(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Run git push origin main."), encoding="utf-8")
        before = f.read_bytes()
        self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(f.read_bytes(), before)

    def test_cli_spawns_nothing(self):
        f = self.tmp / "latest.md"
        f.write_text(_cmd("Clean the workspace with rm -rf build/."),
                     encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            rc, out = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["overall_status"], "blocked")
        mock_run.assert_not_called()


if __name__ == "__main__":
    print("X6-D2 tests — command gates (classification only, never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
