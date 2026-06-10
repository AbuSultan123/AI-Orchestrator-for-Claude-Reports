"""
Tests for Auto-Exchange X4: brief watcher loop.

Run: python tests/test_auto_exchange_x4.py

All OpenAI calls are mocked. No real OPENAI_API_KEY required.
No Claude Code execution. No BRIDGE_EXECUTE_ENABLED=1 required.
sleep is injected to avoid real delays.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import auto_exchange as ax


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SAMPLE_BRIEF_V1 = """\
# ChatGPT Brief
## Recommended next action
Run the tests and confirm they pass.
---
Please review this brief and tell me the next safest step.
"""

_SAMPLE_BRIEF_V2 = """\
# ChatGPT Brief
## Recommended next action
Update docs/BRIDGE-MODE-v0.3-CURRENT-STATUS.md with the latest status.
---
Please review this brief and tell me the next safest step.
"""

_CONFIG = {
    "planner": {"openai": {"model": "gpt-4o-mini", "max_output_tokens": 512, "timeout_seconds": 10}},
    "approvals_dir": "approvals",
    "logs_dir": "logs",
}


class _X4TestBase(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)

        self.brief_path   = self.tmp / "latest-brief.md"
        self.command_path = self.tmp / "chatgpt-commands" / "latest.md"
        self.history_dir  = self.tmp / "chatgpt-command-history"
        self.approvals    = self.tmp / "approvals"
        self.state_dir    = self.tmp / "state"
        self.status_path  = self.state_dir / "auto-exchange-status.json"

        self.config = dict(_CONFIG)
        self.config["approvals_dir"] = str(self.approvals)
        self.config["logs_dir"]      = str(self.tmp / "logs")

        self._sleep_calls = []

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _no_sleep(self, secs):
        self._sleep_calls.append(secs)

    def _run_watch(self, max_cycles=3, planner="local", env=None, interval=0):
        if env is None:
            env = {}
        return ax.watch_briefs(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            approvals_dir=self.approvals,
            state_dir=self.state_dir,
            config=self.config,
            env=env,
            planner=planner,
            interval=interval,
            max_cycles=max_cycles,
            _sleep_fn=self._no_sleep,
            _print_fn=lambda *a, **k: None,
        )

    def _run_watch_openai(self, max_cycles=3, mock_content=None):
        if mock_content is None:
            mock_content = (
                "# Next Claude Code Instruction\n\n"
                "Run the test suite and confirm all tests pass.\n\n"
                "## Scope\ndocs/ only.\n\n"
                "## Forbidden\n"
                "- No git push, git tag, gh release, or PR unless explicitly requested.\n"
                "- No real Claude Code execution.\n"
                "- Do not use --runner execute or set BRIDGE_EXECUTE_ENABLED=1.\n"
                "- Stop on ambiguity, high risk, or forbidden actions.\n"
            )
        env = {"OPENAI_API_KEY": "sk-test-key-for-unit-tests-only"}
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        with patch("auto_exchange.call_openai", return_value=(mock_content, 55)):
            with patch("auto_exchange.log_api_call"):
                return ax.watch_briefs(
                    brief_path=self.brief_path,
                    command_path=self.command_path,
                    history_dir=self.history_dir,
                    approvals_dir=self.approvals,
                    state_dir=self.state_dir,
                    config=self.config,
                    env=env,
                    planner="openai",
                    interval=0,
                    max_cycles=max_cycles,
                    _sleep_fn=self._no_sleep,
                    _print_fn=lambda *a, **k: None,
                )


# ---------------------------------------------------------------------------
# 1. Missing brief does not crash; watcher waits
# ---------------------------------------------------------------------------

class TestMissingBriefWaits(_X4TestBase):

    def test_missing_brief_all_cycles_wait(self):
        counts = self._run_watch(max_cycles=3)
        self.assertEqual(counts["cycles"], 3)
        self.assertEqual(counts["commands_generated"], 0)

    def test_missing_brief_status_written(self):
        self._run_watch(max_cycles=2)
        self.assertTrue(self.status_path.exists())

    def test_missing_brief_no_command_file(self):
        self._run_watch(max_cycles=3)
        self.assertFalse(self.command_path.exists())


# ---------------------------------------------------------------------------
# 2. First brief detection triggers X3 local fallback
# ---------------------------------------------------------------------------

class TestFirstBriefDetected(_X4TestBase):

    def test_first_brief_triggers_command(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=2)
        self.assertGreaterEqual(counts["commands_generated"], 1)
        self.assertTrue(self.command_path.exists())

    def test_first_brief_creates_archive(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self._run_watch(max_cycles=2)
        archives = list(self.history_dir.glob("*-command.md"))
        self.assertGreaterEqual(len(archives), 1)


# ---------------------------------------------------------------------------
# 3. Duplicate unchanged brief is skipped
# ---------------------------------------------------------------------------

class TestDuplicateSkip(_X4TestBase):

    def test_same_content_skipped_on_second_cycle(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=3)
        # First cycle: processes. Second and third: duplicate skip.
        self.assertEqual(counts["commands_generated"], 1)
        self.assertGreaterEqual(counts["duplicate_skips"], 1)

    def test_duplicate_skip_count_correct(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=4)
        self.assertEqual(counts["duplicate_skips"], 3)


# ---------------------------------------------------------------------------
# 4. Changed brief triggers a new command
# ---------------------------------------------------------------------------

class TestChangedBriefRetriggers(_X4TestBase):

    def test_changed_brief_produces_second_command(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        # Run once to process v1
        self._run_watch(max_cycles=1)
        # Now update the brief
        self.brief_path.write_text(_SAMPLE_BRIEF_V2, encoding="utf-8")
        # Run again — should detect change and generate a new command
        counts2 = self._run_watch(max_cycles=2)
        self.assertGreaterEqual(counts2["commands_generated"], 1)

    def test_two_distinct_archives_after_two_different_briefs(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self._run_watch(max_cycles=1)
        self.brief_path.write_text(_SAMPLE_BRIEF_V2, encoding="utf-8")
        self._run_watch(max_cycles=1)
        archives = list(self.history_dir.glob("*-command.md"))
        self.assertEqual(len(archives), 2)


# ---------------------------------------------------------------------------
# 5. --max-cycles exits deterministically
# ---------------------------------------------------------------------------

class TestMaxCycles(_X4TestBase):

    def test_max_cycles_2_runs_exactly_2(self):
        counts = self._run_watch(max_cycles=2)
        self.assertEqual(counts["cycles"], 2)

    def test_max_cycles_5_runs_exactly_5(self):
        counts = self._run_watch(max_cycles=5)
        self.assertEqual(counts["cycles"], 5)

    def test_max_cycles_1_with_brief_generates_command(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=1)
        self.assertEqual(counts["cycles"], 1)
        self.assertEqual(counts["commands_generated"], 1)


# ---------------------------------------------------------------------------
# 6. Pending approval pauses processing
# ---------------------------------------------------------------------------

class TestPendingApprovalPauses(_X4TestBase):

    def test_pending_approval_prevents_command(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self.approvals.mkdir(parents=True, exist_ok=True)
        (self.approvals / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")
        counts = self._run_watch(max_cycles=3)
        self.assertEqual(counts["commands_generated"], 0)
        self.assertGreaterEqual(counts["approval_pauses"], 1)

    def test_pending_approval_count_matches_cycles(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self.approvals.mkdir(parents=True, exist_ok=True)
        (self.approvals / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")
        counts = self._run_watch(max_cycles=4)
        self.assertEqual(counts["approval_pauses"], 4)


# ---------------------------------------------------------------------------
# 7. Clearing pending approval resumes processing
# ---------------------------------------------------------------------------

class TestApprovalClearResumes(_X4TestBase):

    def test_clear_approval_allows_command(self):
        # First run: pending approval blocks
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self.approvals.mkdir(parents=True, exist_ok=True)
        (self.approvals / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")
        counts1 = self._run_watch(max_cycles=2)
        self.assertEqual(counts1["commands_generated"], 0)

        # Clear approval — second run should process
        (self.approvals / "PENDING_APPROVAL.md").unlink()
        counts2 = self._run_watch(max_cycles=2)
        self.assertEqual(counts2["commands_generated"], 1)

    def test_command_written_after_approval_cleared(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self.approvals.mkdir(parents=True, exist_ok=True)
        pa = self.approvals / "PENDING_APPROVAL.md"
        pa.write_text("pending", encoding="utf-8")
        self._run_watch(max_cycles=1)
        self.assertFalse(self.command_path.exists())

        pa.unlink()
        self._run_watch(max_cycles=1)
        self.assertTrue(self.command_path.exists())


# ---------------------------------------------------------------------------
# 8. Local-only mode requires no OpenAI key
# ---------------------------------------------------------------------------

class TestLocalOnlyNoKey(_X4TestBase):

    def test_local_no_key_runs_successfully(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=2, planner="local", env={})
        self.assertEqual(counts["commands_generated"], 1)

    def test_local_no_key_writes_command(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        self._run_watch(max_cycles=1, planner="local", env={})
        self.assertTrue(self.command_path.exists())


# ---------------------------------------------------------------------------
# 9. OpenAI mode missing key fails safely
# ---------------------------------------------------------------------------

class TestOpenAIMissingKeySafe(_X4TestBase):

    def test_missing_key_no_command_written(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=2, planner="openai", env={})
        self.assertEqual(counts["commands_generated"], 0)
        self.assertFalse(self.command_path.exists())

    def test_missing_key_no_crash(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        # Should return without raising
        try:
            self._run_watch(max_cycles=2, planner="openai", env={})
        except Exception as exc:
            self.fail(f"watch_briefs raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# 10. Generated command is never executed
# ---------------------------------------------------------------------------

class TestCommandNeverExecuted(_X4TestBase):

    def test_no_subprocess_calls(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            with patch("subprocess.Popen") as mock_popen:
                self._run_watch(max_cycles=2)
                self.assertEqual(mock_run.call_count, 0)
                self.assertEqual(mock_popen.call_count, 0)

    def test_result_has_no_execution_keys(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        counts = self._run_watch(max_cycles=1)
        self.assertNotIn("ran", counts)
        self.assertNotIn("executed", counts)


# ---------------------------------------------------------------------------
# 11. No Claude execution happens
# ---------------------------------------------------------------------------

class TestNoClaudeExecution(_X4TestBase):

    def test_no_claude_binary_called(self):
        self.brief_path.write_text(_SAMPLE_BRIEF_V1, encoding="utf-8")
        with patch("subprocess.run") as mock_run:
            self._run_watch(max_cycles=2)
            for call in mock_run.call_args_list:
                args = call[0][0] if call[0] else []
                if isinstance(args, (list, tuple)):
                    self.assertFalse(
                        any("claude" in str(a).lower() for a in args),
                        f"claude binary called: {args}",
                    )

    def test_openai_mode_no_claude_called(self):
        counts = self._run_watch_openai(max_cycles=2)
        self.assertGreaterEqual(counts["commands_generated"], 1)
        # No execution key means nothing was run
        self.assertNotIn("ran", counts)


# ---------------------------------------------------------------------------
# 12. Status file records watcher state
# ---------------------------------------------------------------------------

class TestStatusFileWritten(_X4TestBase):

    def test_status_file_written_after_run(self):
        self._run_watch(max_cycles=2)
        self.assertTrue(self.status_path.exists())

    def test_status_file_contains_expected_keys(self):
        self._run_watch(max_cycles=2)
        import json
        data = json.loads(self.status_path.read_text(encoding="utf-8"))
        for key in ("timestamp", "watcher_state", "planner", "cycles_completed",
                    "commands_generated", "duplicate_skips", "approval_pauses"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_status_cycles_match_run(self):
        self._run_watch(max_cycles=4)
        import json
        data = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["cycles_completed"], 4)

    def test_status_state_done_at_end(self):
        self._run_watch(max_cycles=2)
        import json
        data = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(data["watcher_state"], "done")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nAuto-Exchange X4 tests — watch loop")
    print("No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.")
    unittest.main(verbosity=2)
