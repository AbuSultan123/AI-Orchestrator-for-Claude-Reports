"""
X6-D1 tests: command_parser.py -- parse only, never execute.

Run: python tests/test_command_parser_x6d1.py

The parser reads markdown and returns a dict.  These tests verify it never
executes anything, never spawns subprocesses, never makes network calls,
never invokes Claude or OpenAI, and never leaks secrets.
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

import command_parser as cp


_FAKE_SECRET = "sk-test-faketestkey1234567890abcdef"

_SAMPLE = """\
<!-- CHATGPT COMMAND -->
<!-- Generated:  2026-06-10T14:36:26 -->
<!-- Planner:    local -->
<!-- Status:     pending human-reviewed Claude Code read -->
<!-- WARNING:    NOT auto-executed. -->

# Next Claude Code Instruction

Update docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md with the latest test count.
Run tests/test_bridge_phase_d.py and confirm it passes.

## Scope
Limit changes to docs/ and tests/test_bridge_phase_d.py only.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""

_RISKY = """\
# Next Claude Code Instruction

Update the changelog, then run git push origin main to publish it.

## Scope
docs/ only.
"""

_WITH_FENCE = """\
# Next Claude Code Instruction

Run the following:

```
python tests/test_bridge_phase_d.py
python tests/test_bridge_phase_d2.py
```

## Scope
tests/ only.

## Forbidden
- No git push.
"""

_WITH_SECRET = f"""\
# Next Claude Code Instruction

Do the thing.

## Scope
Use OPENAI_API_KEY={_FAKE_SECRET} for the call against docs/.
"""

_MALFORMED = "just some words\nwith no headings at all\nand nothing structured\n"


# ---------------------------------------------------------------------------
# Parsing behavior
# ---------------------------------------------------------------------------

class TestParsing(unittest.TestCase):

    def test_parses_title(self):
        r = cp.parse_command(_SAMPLE)
        self.assertEqual(r["title"], "Next Claude Code Instruction")
        self.assertEqual(r["parse_status"], "ok")

    def test_parses_allowed_paths_from_scope(self):
        r = cp.parse_command(_SAMPLE)
        self.assertIn("docs/", r["allowed_paths"])
        self.assertIn("tests/test_bridge_phase_d.py", r["allowed_paths"])

    def test_parses_guardrails(self):
        r = cp.parse_command(_SAMPLE)
        self.assertEqual(len(r["guardrails"]), 5)
        self.assertTrue(any("No git push" in g for g in r["guardrails"]))
        self.assertTrue(any("Stop on ambiguity" in g for g in r["guardrails"]))

    def test_baseline_forbidden_paths_always_present(self):
        for text in (_SAMPLE, _MALFORMED, ""):
            r = cp.parse_command(text)
            for p in (".git/", ".env", "TradingView Light/",
                      "pinescript-agents/"):
                self.assertIn(p, r["forbidden_paths"], f"missing {p}")

    def test_parses_required_tests(self):
        r = cp.parse_command(_SAMPLE)
        self.assertEqual(r["required_tests"],
                         ["python tests/test_bridge_phase_d.py"])

    def test_parses_fenced_commands_without_executing(self):
        r = cp.parse_command(_WITH_FENCE)
        self.assertEqual(r["commands"],
                         ["python tests/test_bridge_phase_d.py",
                          "python tests/test_bridge_phase_d2.py"])
        self.assertEqual(len(r["required_tests"]), 2)

    def test_mode_and_approval_are_hardwired(self):
        for text in (_SAMPLE, _RISKY, _MALFORMED):
            r = cp.parse_command(text)
            self.assertEqual(r["mode"], "manual_review")
            self.assertTrue(r["requires_human_approval"])

    def test_hash_is_deterministic_and_distinct(self):
        a1 = cp.parse_command(_SAMPLE)
        a2 = cp.parse_command(_SAMPLE)
        b  = cp.parse_command(_RISKY)
        self.assertEqual(a1["raw_source_hash"], a2["raw_source_hash"])
        self.assertEqual(a1["task_id"], a2["task_id"])
        self.assertNotEqual(a1["raw_source_hash"], b["raw_source_hash"])
        self.assertEqual(a1["task_id"], a1["raw_source_hash"][:16])


# ---------------------------------------------------------------------------
# Degraded inputs
# ---------------------------------------------------------------------------

class TestDegradedInputs(unittest.TestCase):

    def test_missing_scope_warns_but_parses(self):
        text = "# Title\n\nDo a safe thing in docs/.\n"
        r = cp.parse_command(text)
        self.assertIn("missing Scope section", r["parse_warnings"])
        self.assertIn("missing Forbidden/guardrails section",
                      r["parse_warnings"])
        self.assertEqual(r["parse_status"], "ok",
                         "missing optional sections are warnings, not failures")

    def test_empty_text_returns_empty_status(self):
        for text in ("", "   \n  \n"):
            r = cp.parse_command(text)
            self.assertEqual(r["parse_status"], "empty")

    def test_malformed_markdown_needs_review(self):
        r = cp.parse_command(_MALFORMED)
        self.assertEqual(r["parse_status"], "needs_review")
        self.assertTrue(any("no level-1 title" in w
                            for w in r["parse_warnings"]))

    def test_execution_risk_language_needs_review(self):
        r = cp.parse_command(_RISKY)
        self.assertEqual(r["parse_status"], "needs_review")
        self.assertTrue(any("execution-risk language" in w
                            for w in r["parse_warnings"]))
        self.assertTrue(any("git push" in w for w in r["parse_warnings"]))

    def test_guardrail_bullets_do_not_self_trigger(self):
        """The Forbidden section mentions push/execute language but the
        sample must still parse as ok."""
        r = cp.parse_command(_SAMPLE)
        self.assertEqual(r["parse_status"], "ok")
        self.assertFalse(any("execution-risk" in w
                             for w in r["parse_warnings"]))

    def test_non_string_input_is_safe(self):
        r = cp.parse_command(None)  # type: ignore[arg-type]
        self.assertEqual(r["parse_status"], "empty")


# ---------------------------------------------------------------------------
# Safety: never executes, never calls out, never leaks
# ---------------------------------------------------------------------------

class TestSafety(unittest.TestCase):

    def test_parser_never_calls_subprocess_or_system(self):
        with patch("subprocess.run") as mock_run, \
             patch("subprocess.Popen") as mock_popen, \
             patch("os.system") as mock_system:
            cp.parse_command(_SAMPLE)
            cp.parse_command(_RISKY)
            cp.parse_command(_WITH_FENCE)
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()

    def test_parser_never_opens_network_connections(self):
        with patch("urllib.request.urlopen") as mock_open, \
             patch("socket.create_connection") as mock_sock:
            cp.parse_command(_SAMPLE)
            cp.parse_command(_WITH_SECRET)
        mock_open.assert_not_called()
        mock_sock.assert_not_called()

    def test_module_source_has_no_execution_imports(self):
        """The parser module must not even import execution machinery."""
        source = Path(cp.__file__).read_text(encoding="utf-8")
        for needle in ("import subprocess", "import os\n", "urlopen",
                       "openai_planner", "import requests",
                       "_invoke_claude", "shutil.which"):
            self.assertNotIn(needle, source,
                             f"parser source must not contain {needle!r}")

    def test_no_secret_leaks_into_output(self):
        r = cp.parse_command(_WITH_SECRET)
        serialized = json.dumps(r)
        self.assertNotIn(_FAKE_SECRET, serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertEqual(r["parse_status"], "needs_review")
        self.assertTrue(any("secrets-like content" in w
                            for w in r["parse_warnings"]))
        self.assertIn("[REDACTED]", r["scope"])

    def test_hash_computed_without_leaking_secret(self):
        """The raw hash covers the original text; the secret itself never
        appears anywhere in the parsed output."""
        r = cp.parse_command(_WITH_SECRET)
        self.assertEqual(len(r["raw_source_hash"]), 64)
        self.assertNotIn(_FAKE_SECRET, json.dumps(r))


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
            rc = cp.main(argv)
        return rc, buf.getvalue()

    def test_cli_parses_file_and_prints_json(self):
        f = self.tmp / "latest.md"
        f.write_text(_SAMPLE, encoding="utf-8")
        rc, out = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["title"], "Next Claude Code Instruction")
        self.assertEqual(parsed["parse_status"], "ok")

    def test_cli_missing_file_fails_safely(self):
        rc, out = self._run_cli(["--input", str(self.tmp / "nope.md")])
        self.assertEqual(rc, 1)
        parsed = json.loads(out)
        self.assertEqual(parsed["parse_status"], "missing_file")

    def test_cli_does_not_modify_input_file(self):
        f = self.tmp / "latest.md"
        f.write_text(_SAMPLE, encoding="utf-8")
        before = f.read_bytes()
        self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(f.read_bytes(), before)

    def test_cli_spawns_nothing(self):
        f = self.tmp / "latest.md"
        f.write_text(_WITH_FENCE, encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            rc, _ = self._run_cli(["--input", str(f), "--json"])
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()


if __name__ == "__main__":
    print("X6-D1 tests — command parser (parse only, never execute)")
    print("No real Claude invocation.  No OpenAI calls.  No subprocesses.")
    print()
    unittest.main(verbosity=2)
