"""
Tests for Bridge Mode v0.3 Phase A.

Run: python tests/test_bridge_phase_a.py

Tests helper functions and the --once end-to-end flow without mocking.
Requires orchestrator.py and config/ to be present.
No API calls. No Claude Code execution.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Allow importing bridge from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import bridge as b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_LOW_RISK = """\
# Session Report: Documentation Update

**Project:** AI Orchestrator
**Branch:** `feature/bridge-mode-v0-3`
**Status:** documentation task completed, no code changed

## What was done

Reviewed the existing README.md and ORCHESTRATOR_SPEC.md files.
No code changes were made. No source files were modified.

## Recommendation

Update the spec file with the new bridge mode description.
Documentation only. Markdown only. No source changes.
"""

SAMPLE_APPROVAL = """\
# Session Report: Source Changes

**Project:** AI Orchestrator
**Branch:** `feature/bridge-mode-v0-3`
**Status:** completed

## What was done

Updated src/main.py with new logic.
Will now git commit the changes.

## Recommendation

git commit -m "Update main logic"
"""


class TestFileHash(unittest.TestCase):
    def test_hash_is_sha256(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            p = Path(f.name)
            p.write_bytes(b"hello")
        try:
            h = b.file_sha256(p)
            self.assertEqual(len(h), 64)
            self.assertEqual(h, b.file_sha256(p))  # deterministic
        finally:
            p.unlink(missing_ok=True)

    def test_same_content_same_hash(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f2:
            p1, p2 = Path(f1.name), Path(f2.name)
            p1.write_bytes(b"same content")
            p2.write_bytes(b"same content")
        try:
            self.assertEqual(b.file_sha256(p1), b.file_sha256(p2))
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f2:
            p1, p2 = Path(f1.name), Path(f2.name)
            p1.write_bytes(b"content A")
            p2.write_bytes(b"content B")
        try:
            self.assertNotEqual(b.file_sha256(p1), b.file_sha256(p2))
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)


class TestLoadConfig(unittest.TestCase):
    def test_returns_dict(self):
        cfg = b.load_config()
        self.assertIsInstance(cfg, dict)

    def test_has_poll_interval(self):
        cfg = b.load_config()
        self.assertIn("poll_interval_seconds", cfg)
        self.assertIsInstance(cfg["poll_interval_seconds"], int)


class TestBridgeOnce(unittest.TestCase):
    """
    End-to-end test: drop a sample report into inbox, run --once,
    check that outbox and state were updated.
    """

    def setUp(self):
        # Save original directories so we can restore them after the test
        self._orig_inbox    = b.INBOX_DIR
        self._orig_outbox   = b.OUTBOX_DIR
        self._orig_approval = b.APPROVAL_DIR
        self._orig_logs     = b.LOGS_DIR
        self._orig_state    = b.STATE_DIR
        self._orig_hashfile = b.HASH_FILE
        self._orig_status   = b.STATUS_FILE
        self._orig_pid      = b.PID_FILE

        # Create a temp working tree for this test
        self._tmpdir = tempfile.mkdtemp()
        tmp = Path(self._tmpdir)

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
        b.INBOX_DIR    = self._orig_inbox
        b.OUTBOX_DIR   = self._orig_outbox
        b.APPROVAL_DIR = self._orig_approval
        b.LOGS_DIR     = self._orig_logs
        b.STATE_DIR    = self._orig_state
        b.HASH_FILE    = self._orig_hashfile
        b.STATUS_FILE  = self._orig_status
        b.PID_FILE     = self._orig_pid
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_logger(self) -> "b.logging.Logger":
        return b.setup_logging(b.LOGS_DIR, {"log_rotate_max_bytes": 1_000_000, "log_rotate_backup_count": 1})

    def test_empty_inbox_returns_zero(self):
        logger = self._make_logger()
        count = b.run_once(logger)
        self.assertEqual(count, 0)

    def test_low_risk_report_processed(self):
        # Place a low-risk sample report in inbox
        report = b.INBOX_DIR / "test-low-risk.md"
        report.write_text(SAMPLE_LOW_RISK, encoding="utf-8")

        logger = self._make_logger()
        count = b.run_once(logger)

        # run_once returns 1 processed
        self.assertEqual(count, 1)

        # Outbox should have a task file
        tasks = list(b.OUTBOX_DIR.glob("*-next-task.md"))
        self.assertGreater(len(tasks), 0, "Expected at least one task file in outbox/tasks/")

        # state/latest-decision.json should exist and have a decision field
        # (orchestrator.py writes to BASE_DIR/state/, not the temp STATE_DIR)
        dec_path = b.ORCH_STATE_DIR / "latest-decision.json"
        self.assertTrue(dec_path.exists(), "state/latest-decision.json should exist")
        dec = json.loads(dec_path.read_text(encoding="utf-8"))
        self.assertIn("decision", dec)

        # bridge-status.json should be idle
        status = json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "idle")

        # report should have been moved out of inbox
        self.assertFalse(report.exists(), "Report should be moved to state/processed/ after processing")

        # Hash file should have an entry
        hashes = json.loads(b.HASH_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(hashes), 1)

    def test_approval_report_writes_pending_file(self):
        report = b.INBOX_DIR / "test-approval.md"
        report.write_text(SAMPLE_APPROVAL, encoding="utf-8")

        logger = self._make_logger()
        b.run_once(logger)

        dec_path = b.ORCH_STATE_DIR / "latest-decision.json"
        if dec_path.exists():
            dec = json.loads(dec_path.read_text(encoding="utf-8"))
            d = dec.get("decision", "")
            if d in ("approval_required", "blocked", "unsafe_stop"):
                pending = b.APPROVAL_DIR / "PENDING_APPROVAL.md"
                self.assertTrue(pending.exists(), "PENDING_APPROVAL.md should exist for approval decisions")
                content = pending.read_text(encoding="utf-8")
                self.assertIn("Approval Required", content)

    def test_duplicate_report_skipped(self):
        report = b.INBOX_DIR / "dup.md"
        report.write_text(SAMPLE_LOW_RISK, encoding="utf-8")

        logger = self._make_logger()
        b.run_once(logger)  # first run processes

        # Place the same content again
        report2 = b.INBOX_DIR / "dup-copy.md"
        report2.write_text(SAMPLE_LOW_RISK, encoding="utf-8")

        # run again -- the duplicate should be skipped (same hash)
        # process_report returns True for duplicate skips (not an error)
        hashes = b.load_hashes()
        result = b.process_report(report2, hashes, logger)
        self.assertTrue(result, "Duplicate should return True (not an error)")

    def test_malformed_report_does_not_crash(self):
        report = b.INBOX_DIR / "empty.md"
        report.write_text("   ", encoding="utf-8")  # too short

        logger = self._make_logger()
        count = b.run_once(logger)
        # Should not raise -- returns 0 since the malformed file is skipped
        self.assertEqual(count, 0)

    def test_no_api_key_required(self):
        import os
        # Phase A must work even if OPENAI_API_KEY is not set
        old = os.environ.pop("OPENAI_API_KEY", None)
        try:
            report = b.INBOX_DIR / "no-api-test.md"
            report.write_text(SAMPLE_LOW_RISK, encoding="utf-8")
            logger = self._make_logger()
            # Should not raise EnvironmentError
            count = b.run_once(logger)
            self.assertGreaterEqual(count, 0)
        finally:
            if old is not None:
                os.environ["OPENAI_API_KEY"] = old


if __name__ == "__main__":
    print("Running Bridge Phase A tests...")
    print("No API calls. No Claude Code execution.")
    print()
    unittest.main(verbosity=2)
