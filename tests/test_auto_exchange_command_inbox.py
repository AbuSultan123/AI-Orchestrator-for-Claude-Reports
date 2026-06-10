"""
Tests for Auto-Exchange X5.5: command inbox reader / reviewer.

Run: python tests/test_auto_exchange_command_inbox.py

No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.
The read_inbox_command() function never executes command content.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import auto_exchange as ax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_COMMAND = """\
<!-- CHATGPT COMMAND -->
<!-- Generated:  2026-06-10T14:36:26 -->
<!-- Source:     OpenAI planner/reviewer from Claude brief -->
<!-- Planner:    local -->
<!-- Input:      outbox/chatgpt-briefs/latest.md -->
<!-- Status:     pending human-reviewed Claude Code read -->
<!-- WARNING:    NOT auto-executed. -->

# Next Claude Code Instruction

Review the brief context and write a final status report only.

## Scope
Limit changes to the current project only. Do not modify unrelated files.

## Forbidden
- No git push, git tag, gh release, or PR creation unless explicitly requested.
- No OpenAI API calls unless explicitly requested.
- No real Claude Code execution through the bridge.
- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.
- Stop on ambiguity, high risk, or forbidden actions.
"""

_FORBIDDEN_COMMAND = """\
<!-- CHATGPT COMMAND -->
<!-- Generated:  2026-06-10T14:36:26 -->
<!-- Status:     pending human-reviewed Claude Code read -->

# Next Claude Code Instruction

Run git push origin main and deploy the changes.

## Scope
Everything.
"""


class _InboxTestBase(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)

        self.command_path  = self.tmp / "chatgpt-commands" / "latest.md"
        self.approvals_dir = self.tmp / "approvals"

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _review(self) -> dict:
        return ax.read_inbox_command(
            command_path=self.command_path,
            approvals_dir=self.approvals_dir,
        )

    def _write_command(self, content: str = _SAFE_COMMAND) -> None:
        self.command_path.parent.mkdir(parents=True, exist_ok=True)
        self.command_path.write_text(content, encoding="utf-8")

    def _write_pending_approval(self) -> None:
        self.approvals_dir.mkdir(parents=True, exist_ok=True)
        (self.approvals_dir / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Missing command exits safely with MISSING_COMMAND status
# ---------------------------------------------------------------------------

class TestMissingCommand(_InboxTestBase):

    def test_missing_command_review_status(self):
        result = self._review()
        self.assertEqual(result["review_status"], "MISSING_COMMAND")

    def test_missing_command_exists_false(self):
        result = self._review()
        self.assertFalse(result["exists"])

    def test_missing_command_no_exception(self):
        try:
            self._review()
        except Exception as exc:
            self.fail(f"read_inbox_command raised unexpectedly: {exc}")

    def test_missing_command_path_returned(self):
        result = self._review()
        self.assertEqual(result["path"], str(self.command_path))


# ---------------------------------------------------------------------------
# 2. Safe command shows READY_FOR_HUMAN_REVIEW
# ---------------------------------------------------------------------------

class TestSafeCommand(_InboxTestBase):

    def test_safe_command_ready_for_review(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["review_status"], "READY_FOR_HUMAN_REVIEW")

    def test_safe_command_exists_true(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertTrue(result["exists"])

    def test_safe_command_safe_true(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertTrue(result["safe"])

    def test_safe_command_no_block_reason(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["block_reason"], "")


# ---------------------------------------------------------------------------
# 3. Forbidden command shows BLOCKED_FOR_REVIEW
# ---------------------------------------------------------------------------

class TestForbiddenCommand(_InboxTestBase):

    def test_forbidden_command_blocked(self):
        self._write_command(_FORBIDDEN_COMMAND)
        result = self._review()
        self.assertEqual(result["review_status"], "BLOCKED_FOR_REVIEW")

    def test_forbidden_command_safe_false(self):
        self._write_command(_FORBIDDEN_COMMAND)
        result = self._review()
        self.assertFalse(result["safe"])

    def test_forbidden_command_block_reason_set(self):
        self._write_command(_FORBIDDEN_COMMAND)
        result = self._review()
        self.assertNotEqual(result["block_reason"], "")

    def test_forbidden_command_exists_true(self):
        self._write_command(_FORBIDDEN_COMMAND)
        result = self._review()
        self.assertTrue(result["exists"])


# ---------------------------------------------------------------------------
# 4. Pending approval file shows PENDING_APPROVAL_ACTIVE
# ---------------------------------------------------------------------------

class TestPendingApproval(_InboxTestBase):

    def test_pending_approval_active_status(self):
        self._write_command(_SAFE_COMMAND)
        self._write_pending_approval()
        result = self._review()
        self.assertEqual(result["review_status"], "PENDING_APPROVAL_ACTIVE")

    def test_pending_approval_flag_true(self):
        self._write_command(_SAFE_COMMAND)
        self._write_pending_approval()
        result = self._review()
        self.assertTrue(result["pending_approval"])

    def test_pending_approval_overrides_safe(self):
        # Even a safe command shows PENDING_APPROVAL_ACTIVE when approval file exists
        self._write_command(_SAFE_COMMAND)
        self._write_pending_approval()
        result = self._review()
        self.assertEqual(result["review_status"], "PENDING_APPROVAL_ACTIVE")

    def test_no_pending_approval_flag_absent(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertFalse(result["pending_approval"])


# ---------------------------------------------------------------------------
# 5. Script does not execute command text
# ---------------------------------------------------------------------------

class TestNoExecution(_InboxTestBase):

    def test_no_subprocess_run_called(self):
        self._write_command(_SAFE_COMMAND)
        with patch("subprocess.run") as mock_run:
            with patch("subprocess.Popen") as mock_popen:
                self._review()
                self.assertEqual(mock_run.call_count, 0)
                self.assertEqual(mock_popen.call_count, 0)

    def test_forbidden_command_not_executed(self):
        self._write_command(_FORBIDDEN_COMMAND)
        with patch("subprocess.run") as mock_run:
            self._review()
            self.assertEqual(mock_run.call_count, 0)

    def test_result_has_no_execution_output(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertNotIn("stdout", result)
        self.assertNotIn("returncode", result)
        self.assertNotIn("executed", result)


# ---------------------------------------------------------------------------
# 6. Script does not require OpenAI key
# ---------------------------------------------------------------------------

class TestNoOpenAIRequired(_InboxTestBase):

    def test_no_key_safe_command_succeeds(self):
        self._write_command(_SAFE_COMMAND)
        # Ensure OPENAI_API_KEY is not in env for this call
        with patch.dict("os.environ", {}, clear=False):
            os_env_backup = dict(__import__("os").environ)
            __import__("os").environ.pop("OPENAI_API_KEY", None)
            try:
                result = self._review()
            finally:
                __import__("os").environ.update(os_env_backup)
        self.assertEqual(result["review_status"], "READY_FOR_HUMAN_REVIEW")

    def test_no_key_missing_command_succeeds(self):
        try:
            result = self._review()
        except Exception as exc:
            self.fail(f"Should not need API key for read_inbox_command: {exc}")
        self.assertEqual(result["review_status"], "MISSING_COMMAND")

    def test_result_contains_no_api_key(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        dumped = json.dumps(result)
        self.assertNotIn("sk-", dumped)
        self.assertNotIn("OPENAI_API_KEY", dumped)


# ---------------------------------------------------------------------------
# 7. Script does not require Claude binary
# ---------------------------------------------------------------------------

class TestNoClaudeRequired(_InboxTestBase):

    def test_no_claude_subprocess_call(self):
        self._write_command(_SAFE_COMMAND)
        with patch("subprocess.run") as mock_run:
            self._review()
            for call in mock_run.call_args_list:
                args = call[0][0] if call[0] else []
                if isinstance(args, (list, tuple)):
                    self.assertFalse(
                        any("claude" in str(a).lower() for a in args),
                        f"claude binary called unexpectedly: {args}",
                    )

    def test_review_works_with_no_path_modifications(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertIn("review_status", result)


# ---------------------------------------------------------------------------
# 8. Full body included in result (for -Full/-Raw display)
# ---------------------------------------------------------------------------

class TestFullBodyInResult(_InboxTestBase):

    def test_body_contains_command_content(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertIn("Next Claude Code Instruction", result["body"])

    def test_body_strips_html_comment_headers(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertNotIn("<!-- CHATGPT COMMAND -->", result["body"])
        self.assertNotIn("<!-- Generated:", result["body"])

    def test_body_nonempty_for_safe_command(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertTrue(len(result["body"]) > 0)

    def test_body_empty_when_missing(self):
        result = self._review()
        self.assertEqual(result["body"], "")


# ---------------------------------------------------------------------------
# 9. HTML header fields parsed correctly
# ---------------------------------------------------------------------------

class TestHeaderParsing(_InboxTestBase):

    def test_status_header_parsed(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["status_header"], "pending human-reviewed Claude Code read")

    def test_source_header_parsed(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["source_header"], "OpenAI planner/reviewer from Claude brief")

    def test_planner_header_parsed(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["planner_header"], "local")

    def test_warning_header_parsed(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertIn("NOT auto-executed", result["warning_header"])

    def test_missing_headers_return_empty_strings(self):
        minimal = "# Minimal Command\n\nDo a thing.\n"
        self._write_command(minimal)
        result = self._review()
        self.assertEqual(result["status_header"],  "")
        self.assertEqual(result["source_header"],  "")
        self.assertEqual(result["planner_header"], "")
        self.assertEqual(result["warning_header"], "")


# ---------------------------------------------------------------------------
# 10. Title extracted from first markdown heading
# ---------------------------------------------------------------------------

class TestTitleExtraction(_InboxTestBase):

    def test_title_extracted_from_heading(self):
        self._write_command(_SAFE_COMMAND)
        result = self._review()
        self.assertEqual(result["title"], "Next Claude Code Instruction")

    def test_title_empty_when_no_heading(self):
        self._write_command("Just some text with no heading.\n")
        result = self._review()
        self.assertEqual(result["title"], "")

    def test_title_not_from_comment_heading(self):
        # A comment that looks like a heading should not be used as title
        content = "<!-- # Not a real heading -->\n# Real Title\n\nContent.\n"
        self._write_command(content)
        result = self._review()
        self.assertEqual(result["title"], "Real Title")

    def test_title_from_custom_command(self):
        content = "<!-- Status: pending -->\n\n# My Task\n\nDo something safe.\n"
        self._write_command(content)
        result = self._review()
        self.assertEqual(result["title"], "My Task")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nAuto-Exchange X5.5 tests — command inbox reader/reviewer")
    print("No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.")
    unittest.main(verbosity=2)
