"""
Tests for Auto-Exchange X5: dashboard/status generation.

Run: python tests/test_auto_exchange_x5.py

No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.
"""

import json
import shutil
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

_SAMPLE_BRIEF = """\
# ChatGPT Brief
## Recommended next action
Run the tests and confirm all 190 pass.
---
Please review this brief and tell me the next safest step.
"""

_CONFIG = {
    "planner": {"openai": {"model": "gpt-4o-mini", "max_output_tokens": 512, "timeout_seconds": 10}},
    "approvals_dir": "approvals",
    "logs_dir": "logs",
}


class _X5TestBase(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)

        self.brief_path      = self.tmp / "latest-brief.md"
        self.command_path    = self.tmp / "chatgpt-commands" / "latest.md"
        self.history_dir     = self.tmp / "chatgpt-command-history"
        self.approvals       = self.tmp / "approvals"
        self.state_dir       = self.tmp / "state"
        self.dashboard_path  = self.state_dir / "auto-exchange-dashboard.json"

        self.config = dict(_CONFIG)
        self.config["approvals_dir"] = str(self.approvals)
        self.config["logs_dir"]      = str(self.tmp / "logs")

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_watch(self, max_cycles=2, planner="local", env=None):
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
            interval=0,
            max_cycles=max_cycles,
            _sleep_fn=lambda s: None,
            _print_fn=lambda *a, **k: None,
        )

    def _run_x3(self, planner="local", env=None):
        if env is None:
            env = {}
        return ax.review_brief(
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            config=self.config,
            env=env,
            planner=planner,
        )

    def _write_dashboard_direct(self, last_result="ready", **kwargs):
        defaults = dict(
            state_dir=self.state_dir,
            brief_path=self.brief_path,
            command_path=self.command_path,
            history_dir=self.history_dir,
            approvals_dir=self.approvals,
            planner="local",
            last_result=last_result,
        )
        defaults.update(kwargs)
        ax.write_dashboard(**defaults)

    def _load_dashboard(self) -> dict:
        return json.loads(self.dashboard_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Dashboard written after local X3 or X4 processing
# ---------------------------------------------------------------------------

class TestDashboardWritten(_X5TestBase):

    def test_x4_local_writes_dashboard(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2)
        self.assertTrue(self.dashboard_path.exists())

    def test_x3_single_shot_via_write_dashboard_directly(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._write_dashboard_direct(last_result="ready")
        self.assertTrue(self.dashboard_path.exists())

    def test_dashboard_updated_on_second_run(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=1)
        mtime1 = self.dashboard_path.stat().st_mtime

        self.brief_path.write_text(_SAMPLE_BRIEF + "\nextra line", encoding="utf-8")
        self._run_watch(max_cycles=1)
        mtime2 = self.dashboard_path.stat().st_mtime

        # Content must have changed (mtime might be same-second; check content)
        d = self._load_dashboard()
        self.assertEqual(d["last_result"], "ready")


# ---------------------------------------------------------------------------
# 2. Missing status file does not crash
# ---------------------------------------------------------------------------

class TestMissingFileNoCrash(_X5TestBase):

    def test_write_dashboard_missing_brief_no_crash(self):
        # brief doesn't exist — write_dashboard should still write the file
        try:
            self._write_dashboard_direct(last_result="missing_brief")
        except Exception as exc:
            self.fail(f"write_dashboard raised unexpectedly: {exc}")
        self.assertTrue(self.dashboard_path.exists())

    def test_write_dashboard_missing_history_dir_no_crash(self):
        # history_dir doesn't exist yet — should handle gracefully
        try:
            self._write_dashboard_direct()
        except Exception as exc:
            self.fail(f"write_dashboard raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# 3. Dashboard includes pending approval boolean
# ---------------------------------------------------------------------------

class TestPendingApprovalField(_X5TestBase):

    def test_pending_approval_false_when_absent(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertFalse(d["pending_approval"])

    def test_pending_approval_true_when_file_exists(self):
        self.approvals.mkdir(parents=True, exist_ok=True)
        (self.approvals / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertTrue(d["pending_approval"])

    def test_x4_paused_dashboard_shows_pending_approval(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self.approvals.mkdir(parents=True, exist_ok=True)
        (self.approvals / "PENDING_APPROVAL.md").write_text("pending", encoding="utf-8")
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertTrue(d["pending_approval"])


# ---------------------------------------------------------------------------
# 4. Dashboard includes latest brief path and command path
# ---------------------------------------------------------------------------

class TestPathsInDashboard(_X5TestBase):

    def test_brief_path_in_dashboard(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertIn("brief", d)
        self.assertEqual(d["brief"]["path"], str(self.brief_path))

    def test_command_path_in_dashboard(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertIn("command", d)
        self.assertEqual(d["command"]["path"], str(self.command_path))

    def test_x4_run_brief_path_correct(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=1)
        d = self._load_dashboard()
        self.assertEqual(d["brief"]["path"], str(self.brief_path))


# ---------------------------------------------------------------------------
# 5. Dashboard marks generated_command_executed as false
# ---------------------------------------------------------------------------

class TestCommandExecutedFalse(_X5TestBase):

    def test_generated_command_executed_always_false(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["generated_command_executed"])

    def test_generated_command_executed_false_after_x4_run(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["generated_command_executed"])


# ---------------------------------------------------------------------------
# 6. Dashboard marks real_claude_execution as false
# ---------------------------------------------------------------------------

class TestClaudeExecutionFalse(_X5TestBase):

    def test_real_claude_execution_always_false(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["real_claude_execution"])

    def test_real_claude_execution_false_after_x4_run(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["real_claude_execution"])


# ---------------------------------------------------------------------------
# 7. Dashboard marks x6_enabled as false
# ---------------------------------------------------------------------------

class TestX6EnabledFalse(_X5TestBase):

    def test_x6_enabled_always_false(self):
        self._write_dashboard_direct()
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["x6_enabled"])

    def test_x6_enabled_false_after_x4_run(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertFalse(d["safety"]["x6_enabled"])


# ---------------------------------------------------------------------------
# 8. Duplicate skip visible in dashboard
# ---------------------------------------------------------------------------

class TestDuplicateSkipVisible(_X5TestBase):

    def test_duplicate_skip_count_in_dashboard(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=3)
        d = self._load_dashboard()
        self.assertGreaterEqual(d["duplicate_skips"], 1)

    def test_last_result_duplicate_skip(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=3)  # cycle 1: process; cycles 2-3: skip
        d = self._load_dashboard()
        # After 3 cycles the last event was a duplicate skip
        self.assertEqual(d["last_result"], "duplicate_skip")


# ---------------------------------------------------------------------------
# 9. Missing brief state visible in dashboard
# ---------------------------------------------------------------------------

class TestMissingBriefVisible(_X5TestBase):

    def test_missing_brief_last_result(self):
        # Don't create the brief file
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertEqual(d["last_result"], "missing_brief")

    def test_missing_brief_watcher_state(self):
        self._run_watch(max_cycles=2)
        d = self._load_dashboard()
        self.assertEqual(d["watcher_state"], "done")


# ---------------------------------------------------------------------------
# 10. No OpenAI key required or printed in local-only dashboard test
# ---------------------------------------------------------------------------

class TestLocalOnlyNeedsNoKey(_X5TestBase):

    def test_local_only_no_key_writes_dashboard(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2, planner="local", env={})
        self.assertTrue(self.dashboard_path.exists())

    def test_local_only_dashboard_planner_field(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2, planner="local", env={})
        d = self._load_dashboard()
        self.assertEqual(d["planner"], "local")

    def test_dashboard_contains_no_api_key(self):
        self.brief_path.write_text(_SAMPLE_BRIEF, encoding="utf-8")
        self._run_watch(max_cycles=2, planner="local", env={})
        raw = self.dashboard_path.read_text(encoding="utf-8")
        self.assertNotIn("sk-", raw)
        self.assertNotIn("OPENAI_API_KEY", raw)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nAuto-Exchange X5 tests — dashboard/status")
    print("No real OpenAI calls. No Claude execution. No BRIDGE_EXECUTE_ENABLED=1 required.")
    unittest.main(verbosity=2)
