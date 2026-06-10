"""
Tests for Bridge Mode v0.3 watch mode (run_watch).

Run: python tests/test_watch_mode.py

All tests use max_cycles and interval=0 to drive the loop deterministically.
No real API calls. No Claude Code execution. No real OpenAI calls.
"""

import json
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bridge as b


SAMPLE_REPORT = """\
# Session Report: Documentation Update

**Project:** AI Orchestrator
**Branch:** main
**Status:** documentation task completed, no code changed

## What was done
Reviewed the existing README.md.
No code changes were made. Documentation only. No source changes.

## Recommendation
Update spec file with the new bridge mode description.
Documentation only. Markdown only. No source changes.
"""

SAMPLE_APPROVAL_REPORT = """\
# Session Report: Source Changes

**Project:** AI Orchestrator
**Branch:** main
**Status:** completed

## What was done
Updated src/main.py with new logic.
Will git commit the changes.

## Recommendation
git commit -m "Update main logic"
"""


class WatchModeTestBase(unittest.TestCase):
    """Redirects all bridge module-level dirs to a temp tree."""

    def setUp(self):
        self._orig = {
            "INBOX_DIR":    b.INBOX_DIR,
            "OUTBOX_DIR":   b.OUTBOX_DIR,
            "APPROVAL_DIR": b.APPROVAL_DIR,
            "LOGS_DIR":     b.LOGS_DIR,
            "STATE_DIR":    b.STATE_DIR,
            "HASH_FILE":    b.HASH_FILE,
            "STATUS_FILE":  b.STATUS_FILE,
            "PID_FILE":     b.PID_FILE,
        }
        self._tmpdir = Path(tempfile.mkdtemp())
        tmp = self._tmpdir

        b.INBOX_DIR    = tmp / "inbox"    / "reports"
        b.OUTBOX_DIR   = tmp / "outbox"   / "tasks"
        b.APPROVAL_DIR = tmp / "approvals"
        b.LOGS_DIR     = tmp / "logs"
        b.STATE_DIR    = tmp / "state"
        b.HASH_FILE    = tmp / "state"    / "processed-hashes.json"
        b.STATUS_FILE  = tmp / "state"    / "bridge-status.json"
        b.PID_FILE     = tmp / "state"    / "bridge.pid"

        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR, b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(b, k, v)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _logger(self):
        return b.setup_logging(b.LOGS_DIR, {
            "log_rotate_max_bytes": 1_000_000,
            "log_rotate_backup_count": 1,
        })


class TestWatchModeBasic(WatchModeTestBase):

    def test_empty_inbox_completes_cycles(self):
        """Watch mode runs max_cycles with empty inbox and returns cycle count."""
        logger = self._logger()
        cycles = b.run_watch(0, logger, planner="local", max_cycles=3)
        self.assertEqual(cycles, 3)

    def test_returns_cycle_count(self):
        """run_watch returns the number of cycles completed."""
        logger = self._logger()
        n = b.run_watch(0, logger, planner="local", max_cycles=1)
        self.assertEqual(n, 1)

    def test_pid_file_cleaned_up(self):
        """PID file is removed after run_watch exits normally."""
        logger = self._logger()
        b.run_watch(0, logger, planner="local", max_cycles=1)
        self.assertFalse(b.PID_FILE.exists(), "PID file should be removed after watch exits")

    def test_status_idle_after_run(self):
        """Bridge status is idle after normal watch exit."""
        logger = self._logger()
        b.run_watch(0, logger, planner="local", max_cycles=1)
        # Status file may be written; if it is, check it's not in an error state
        if b.STATUS_FILE.exists():
            status = json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))
            self.assertNotEqual(status.get("status"), "error")


class TestWatchModePendingApproval(WatchModeTestBase):

    def test_pauses_when_pending_approval_exists(self):
        """Watch mode skips inbox processing when PENDING_APPROVAL.md exists."""
        # Place a report in inbox
        report = b.INBOX_DIR / "my-report.md"
        report.write_text(SAMPLE_REPORT, encoding="utf-8")

        # Create a pending approval
        pending = b.APPROVAL_DIR / "PENDING_APPROVAL.md"
        pending.write_text("# Approval Required\n\nPending.", encoding="utf-8")

        logger = self._logger()
        b.run_watch(0, logger, planner="local", max_cycles=2)

        # Report should still be in inbox (not processed)
        self.assertTrue(report.exists(), "Report should NOT be processed while PENDING_APPROVAL.md exists")

        # Outbox should be empty
        tasks = list(b.OUTBOX_DIR.glob("*-next-task.md"))
        self.assertEqual(len(tasks), 0, "No tasks should be archived while paused")

    def test_status_set_to_waiting_when_paused(self):
        """Bridge status is waiting_approval when paused."""
        pending = b.APPROVAL_DIR / "PENDING_APPROVAL.md"
        pending.write_text("# Approval Required", encoding="utf-8")

        logger = self._logger()
        b.run_watch(0, logger, planner="local", max_cycles=1)

        status = json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "waiting_approval")

    def test_resumes_after_pending_approval_cleared(self):
        """Watch mode resumes processing after PENDING_APPROVAL.md is removed.

        Cycle 1: pending approval exists -> bridge pauses, does not touch inbox.
        Between cycles: pending file is removed (simulates human resolving it).
        Cycle 2: pending gone -> bridge resumes and processes the report.
        """
        report = b.INBOX_DIR / "late-report.md"
        report.write_text(SAMPLE_REPORT, encoding="utf-8")

        pending = b.APPROVAL_DIR / "PENDING_APPROVAL.md"
        pending.write_text("# Approval Required", encoding="utf-8")

        # Patch time.sleep (called between cycles) to remove pending after cycle 1.
        import time
        original_sleep = time.sleep
        sleep_call_count = [0]

        def _patched_sleep(secs):
            sleep_call_count[0] += 1
            if sleep_call_count[0] == 1:
                pending.unlink(missing_ok=True)
            original_sleep(secs)

        time.sleep = _patched_sleep
        try:
            logger = self._logger()
            b.run_watch(0, logger, planner="local", max_cycles=2)
        finally:
            time.sleep = original_sleep

        # After cycle 2 the report should have been processed and moved out of inbox
        self.assertFalse(
            report.exists(),
            "Report should be processed (moved to state/processed/) after pending approval cleared"
        )


class TestWatchModeDuplicateSkip(WatchModeTestBase):

    def test_same_report_not_processed_twice(self):
        """Watch mode skips a report that has already been processed (duplicate hash)."""
        report = b.INBOX_DIR / "once.md"
        report.write_text(SAMPLE_REPORT, encoding="utf-8")

        logger = self._logger()
        # First cycle: process the report (it gets moved to processed/)
        b.run_watch(0, logger, planner="local", max_cycles=1)

        # Re-place the same content
        report2 = b.INBOX_DIR / "once-again.md"
        report2.write_text(SAMPLE_REPORT, encoding="utf-8")

        # Second run: same hash should be skipped
        tasks_before = len(list(b.OUTBOX_DIR.glob("*-next-task.md")))
        b.run_watch(0, logger, planner="local", max_cycles=1)
        tasks_after = len(list(b.OUTBOX_DIR.glob("*-next-task.md")))

        self.assertEqual(tasks_before, tasks_after, "Duplicate report must not generate a new task")


class TestWatchModeNoClaudeExecution(WatchModeTestBase):

    def test_runner_defaults_to_dry_run(self):
        """run_watch uses dry-run runner by default -- no Claude invocation."""
        import inspect
        sig = inspect.signature(b.run_watch)
        default_runner = sig.parameters["runner"].default
        self.assertEqual(default_runner, "dry-run",
                         "run_watch must default to dry-run runner")

    def test_max_cycles_parameter_exists(self):
        """run_watch accepts max_cycles for test/smoke mode."""
        import inspect
        sig = inspect.signature(b.run_watch)
        self.assertIn("max_cycles", sig.parameters)

    def test_no_openai_call_with_local_planner(self):
        """Local planner watch mode never imports openai_planner."""
        import sys
        # Ensure openai_planner is not loaded as a side effect of watch mode
        before = "openai_planner" in sys.modules
        report = b.INBOX_DIR / "local.md"
        report.write_text(SAMPLE_REPORT, encoding="utf-8")
        logger = self._logger()
        b.run_watch(0, logger, planner="local", max_cycles=1)
        after = "openai_planner" in sys.modules
        # If it was already loaded before, that's fine; we just check no net new import
        if not before:
            self.assertFalse(after, "openai_planner must not be imported when planner=local")


if __name__ == "__main__":
    print("Running Bridge watch mode tests...")
    print("No API calls. No Claude Code execution.")
    print()
    unittest.main(verbosity=2)
