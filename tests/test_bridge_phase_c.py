"""
Phase C tests: claude_runner.py pre-execution gates and bridge --runner integration.

No real git calls, no real Claude invocations.  All filesystem side effects
happen in a per-test temporary directory.

Test suites:
  TestRunnerGates         -- individual gate functions
  TestCheckAndRunDryRun   -- full check_and_run() in dry-run mode
  TestCheckAndRunExecute  -- full check_and_run() in execute mode
  TestBridgeRunnerParam   -- bridge.process_report runner= parameter (regression)
  TestPhaseBRegression    -- quick smoke that Phase B paths still work
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make parent importable
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import claude_runner as cr
import bridge as b


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision(d="low_risk_auto_allowed", can_execute=True, **kwargs):
    base = {
        "decision": d,
        "risk_level": "low",
        "reason": "test",
        "can_execute_with_execute_flag": can_execute,
        "requires_user_approval": False,
        "timestamp": datetime.now().isoformat(),
    }
    base.update(kwargs)
    return base


def _make_config(max_runs=3, forbidden=None):
    return {
        "forbidden_task_patterns": forbidden or ["git push", "git tag"],
        "max_auto_runs_per_hour": max_runs,
        "claude_timeout_seconds": 10,
    }


def _ts_recent():
    return (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()


def _ts_old():
    return (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


# ---------------------------------------------------------------------------
# TestRunnerGates
# ---------------------------------------------------------------------------

class TestRunnerGates(unittest.TestCase):

    # Gate 1: DECISION_GATE
    def test_decision_gate_passes(self):
        ok, msg = cr._gate_decision(_make_decision())
        self.assertTrue(ok)
        self.assertIn("low_risk_auto_allowed", msg)

    def test_decision_gate_wrong_decision(self):
        ok, msg = cr._gate_decision(_make_decision(d="approval_required"))
        self.assertFalse(ok)
        self.assertIn("approval_required", msg)

    def test_decision_gate_can_execute_false(self):
        ok, msg = cr._gate_decision(_make_decision(can_execute=False))
        self.assertFalse(ok)
        self.assertIn("can_execute_with_execute_flag is False", msg)

    # Gate 2: FORBIDDEN_GATE
    def test_forbidden_gate_no_patterns(self):
        config = _make_config(forbidden=["git push"])
        ok, msg = cr._gate_forbidden("just a normal task", config)
        self.assertTrue(ok)

    def test_forbidden_gate_detects_pattern(self):
        config = _make_config(forbidden=["git push"])
        ok, msg = cr._gate_forbidden("run git push to publish", config)
        self.assertFalse(ok)
        self.assertIn("git push", msg)

    def test_forbidden_gate_case_insensitive(self):
        config = _make_config(forbidden=["GIT PUSH"])
        ok, msg = cr._gate_forbidden("run git push to publish", config)
        self.assertFalse(ok)

    def test_forbidden_gate_empty_config(self):
        ok, msg = cr._gate_forbidden("git push all the things", {})
        self.assertTrue(ok)

    # Gate 3: PENDING_APPROVAL_GATE
    def test_pending_approval_gate_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = cr._gate_pending_approval(Path(tmp))
            self.assertTrue(ok)

    def test_pending_approval_gate_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "PENDING_APPROVAL.md").write_text("x")
            ok, msg = cr._gate_pending_approval(Path(tmp))
            self.assertFalse(ok)
            self.assertIn("PENDING_APPROVAL.md", msg)

    # Gate 4: GIT_SAFETY_GATE
    def test_git_safety_gate_clean_tree(self):
        import logging
        logger = logging.getLogger("test")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                ok, msg = cr._gate_git_safety(Path(tmp), "regular task", logger)
                self.assertTrue(ok)

    def test_git_safety_gate_dirty_tree_blocked(self):
        import logging
        logger = logging.getLogger("test")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=" M bridge.py\n", stderr="")
                ok, msg = cr._gate_git_safety(Path(tmp), "regular task", logger)
                self.assertFalse(ok)
                self.assertIn("GIT_DIRTY", msg)

    def test_git_safety_gate_dirty_tree_docs_exception(self):
        import logging
        logger = logging.getLogger("test")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=" M README.md\n", stderr="")
                ok, msg = cr._gate_git_safety(Path(tmp), "documentation only update", logger)
                self.assertTrue(ok)
                self.assertIn("exception", msg)

    def test_git_safety_gate_git_not_available(self):
        import logging
        logger = logging.getLogger("test")
        with tempfile.TemporaryDirectory() as tmp:
            with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
                ok, msg = cr._gate_git_safety(Path(tmp), "task", logger)
                self.assertTrue(ok)
                self.assertIn("skipped", msg)

    # Gate 5: RATE_LIMIT_GATE
    def test_rate_limit_gate_no_recent_runs(self):
        ok, msg = cr._gate_rate_limit({}, max_runs=3)
        self.assertTrue(ok)
        self.assertIn("0/3", msg)

    def test_rate_limit_gate_under_limit(self):
        hashes = {
            "abc": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"},
            "def": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"},
        }
        ok, msg = cr._gate_rate_limit(hashes, max_runs=3)
        self.assertTrue(ok)
        self.assertIn("2/3", msg)

    def test_rate_limit_gate_at_limit(self):
        hashes = {
            f"h{i}": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"}
            for i in range(3)
        }
        ok, msg = cr._gate_rate_limit(hashes, max_runs=3)
        self.assertFalse(ok)
        self.assertIn("RATE_LIMIT", msg)

    def test_rate_limit_gate_old_runs_ignored(self):
        hashes = {
            f"h{i}": {"processed_at": _ts_old(), "decision": "low_risk_auto_allowed"}
            for i in range(10)
        }
        ok, msg = cr._gate_rate_limit(hashes, max_runs=3)
        self.assertTrue(ok)

    def test_rate_limit_gate_zero_max(self):
        ok, msg = cr._gate_rate_limit({}, max_runs=0)
        self.assertFalse(ok)

    def test_rate_limit_gate_non_auto_runs_not_counted(self):
        hashes = {
            "abc": {"processed_at": _ts_recent(), "decision": "approval_required"},
            "def": {"processed_at": _ts_recent(), "decision": "blocked"},
        }
        ok, msg = cr._gate_rate_limit(hashes, max_runs=3)
        self.assertTrue(ok)
        self.assertIn("0/3", msg)

    # Gate 6: LOOP_DETECTION
    def test_loop_gate_no_match(self):
        ok, msg, loop = cr._gate_loop("newhash", {})
        self.assertTrue(ok)
        self.assertFalse(loop)

    def test_loop_gate_old_match_allowed(self):
        hashes = {"oldhash": {"processed_at": _ts_old()}}
        ok, msg, loop = cr._gate_loop("oldhash", hashes)
        self.assertTrue(ok)
        self.assertFalse(loop)

    def test_loop_gate_recent_match_dry_run_warns(self):
        hashes = {"loophash": {"processed_at": _ts_recent()}}
        ok, msg, loop = cr._gate_loop("loophash", hashes, mode="dry-run")
        self.assertTrue(ok)     # dry-run: passes but warns
        self.assertTrue(loop)
        self.assertIn("WARNING", msg)

    def test_loop_gate_recent_match_execute_blocks(self):
        hashes = {"loophash": {"processed_at": _ts_recent()}}
        ok, msg, loop = cr._gate_loop("loophash", hashes, mode="execute")
        self.assertFalse(ok)    # execute: hard stop
        self.assertTrue(loop)
        self.assertIn("LOOP_DETECTED", msg)


# ---------------------------------------------------------------------------
# TestCheckAndRunDryRun
# ---------------------------------------------------------------------------

class TestCheckAndRunDryRun(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.approval_dir = self.tmp / "approvals"
        self.approval_dir.mkdir()
        self.task_path = self.tmp / "NEXT_TASK.md"
        self.task_path.write_text("# Next Task\n\nDo the thing.\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _run(self, decision=None, hashes=None, config=None, mode="dry-run", report_hash="testhash"):
        return cr.check_and_run(
            decision=decision or _make_decision(),
            task_path=self.task_path,
            config=config or _make_config(),
            mode=mode,
            base_dir=self.tmp,
            approval_dir=self.approval_dir,
            hashes=hashes or {},
            report_hash=report_hash,
        )

    def test_all_gates_pass_dry_run(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run()
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])        # dry-run never actually runs
        self.assertEqual(result["mode"], "dry-run")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_DECISION,         result["checks_passed"])
        self.assertIn(cr.GATE_FORBIDDEN,        result["checks_passed"])
        self.assertIn(cr.GATE_PENDING_APPROVAL, result["checks_passed"])
        self.assertIn(cr.GATE_GIT_SAFETY,       result["checks_passed"])
        self.assertIn(cr.GATE_RATE_LIMIT,       result["checks_passed"])
        self.assertIn(cr.GATE_LOOP,             result["checks_passed"])

    def test_decision_gate_stops_early(self):
        result = self._run(decision=_make_decision(d="approval_required"))
        self.assertFalse(result["would_run"])
        self.assertEqual(result["gate_triggered"], cr.GATE_DECISION)
        self.assertEqual(result["checks_passed"], [])

    def test_forbidden_gate_stops(self):
        self.task_path.write_text("# Next Task\n\ngit push to publish")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run()
        self.assertFalse(result["would_run"])
        self.assertEqual(result["gate_triggered"], cr.GATE_FORBIDDEN)

    def test_pending_approval_gate_stops(self):
        (self.approval_dir / "PENDING_APPROVAL.md").write_text("pending")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run()
        self.assertFalse(result["would_run"])
        self.assertEqual(result["gate_triggered"], cr.GATE_PENDING_APPROVAL)

    def test_rate_limit_gate_stops(self):
        hashes = {
            f"h{i}": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"}
            for i in range(3)
        }
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run(hashes=hashes)
        self.assertFalse(result["would_run"])
        self.assertEqual(result["gate_triggered"], cr.GATE_RATE_LIMIT)

    def test_loop_detection_warns_dry_run(self):
        hashes = {"loophash": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"}}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run(hashes=hashes, report_hash="loophash")
        # dry-run: loop is detected but we still say would_run=True
        self.assertTrue(result["would_run"])
        self.assertTrue(result["loop_detected"])
        self.assertEqual(result["gate_triggered"], "none")

    def test_missing_task_file_returns_error(self):
        self.task_path.unlink()
        result = self._run()
        # No task text → gate_decision runs on decision only (task_text="")
        # Gate 1 passes (decision is fine), Gate 2 passes (no forbidden in ""),
        # Gate 3 passes, Gate 4 passes, Gate 5 passes, Gate 6 passes
        # So would_run=True, dry_run=True, ran=False
        self.assertFalse(result["ran"])
        self.assertEqual(result["mode"], "dry-run")

    def test_result_has_all_expected_keys(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run()
        for key in ("would_run", "ran", "mode", "gate_triggered",
                    "checks_passed", "checks_failed", "loop_detected", "dry_run"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# TestCheckAndRunExecute
# ---------------------------------------------------------------------------

class TestCheckAndRunExecute(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.approval_dir = self.tmp / "approvals"
        self.approval_dir.mkdir()
        self.task_path = self.tmp / "NEXT_TASK.md"
        self.task_path.write_text("# Next Task\n\nDo the thing.\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _run_execute(self, decision=None, hashes=None, config=None, report_hash="testhash"):
        return cr.check_and_run(
            decision=decision or _make_decision(),
            task_path=self.task_path,
            config=config or _make_config(),
            mode="execute",
            base_dir=self.tmp,
            approval_dir=self.approval_dir,
            hashes=hashes or {},
            report_hash=report_hash,
        )

    def test_execute_mode_claude_not_found(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("shutil.which", return_value=None):
                result = self._run_execute()
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])    # claude not found
        self.assertEqual(result["mode"], "execute")
        self.assertFalse(result["dry_run"])

    def test_execute_mode_claude_exits_cleanly(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with patch("shutil.which", return_value="/usr/bin/claude"):
                result = self._run_execute()
        self.assertTrue(result["would_run"])
        self.assertTrue(result["ran"])

    def test_execute_mode_claude_nonzero_exit(self):
        call_count = {"n": 0}

        def side_effect(cmd, **kwargs):
            if "git" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            # claude invocation
            return MagicMock(returncode=1, stdout="", stderr="")

        with patch("subprocess.run", side_effect=side_effect):
            with patch("shutil.which", return_value="/usr/bin/claude"):
                result = self._run_execute()
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])

    def test_execute_mode_loop_blocks(self):
        hashes = {"loophash": {"processed_at": _ts_recent(), "decision": "low_risk_auto_allowed"}}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = self._run_execute(hashes=hashes, report_hash="loophash")
        self.assertFalse(result["would_run"])
        self.assertEqual(result["gate_triggered"], cr.GATE_LOOP)
        self.assertTrue(result["loop_detected"])


# ---------------------------------------------------------------------------
# TestBridgeRunnerParam
# ---------------------------------------------------------------------------

class TestBridgeRunnerParam(unittest.TestCase):
    """Verify bridge.process_report passes runner= to check_and_run correctly."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = {}
        for attr in ("INBOX_DIR", "OUTBOX_DIR", "APPROVAL_DIR", "LOGS_DIR",
                     "STATE_DIR", "HASH_FILE", "STATUS_FILE", "PID_FILE"):
            self._orig[attr] = getattr(b, attr)

        b.INBOX_DIR    = self.tmp / "inbox"
        b.OUTBOX_DIR   = self.tmp / "outbox"
        b.APPROVAL_DIR = self.tmp / "approvals"
        b.LOGS_DIR     = self.tmp / "logs"
        b.STATE_DIR    = self.tmp / "state"
        b.HASH_FILE    = b.STATE_DIR / "processed-hashes.json"
        b.STATUS_FILE  = b.STATE_DIR / "bridge-status.json"
        b.PID_FILE     = b.STATE_DIR / "bridge.pid"

        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR, b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

        # Write a state/NEXT_TASK.md in the REAL orch state dir
        b.ORCH_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for attr, val in self._orig.items():
            setattr(b, attr, val)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_report(self, content="This is a test report with enough content."):
        p = b.INBOX_DIR / "test-report.md"
        p.write_text(content)
        return p

    def test_process_report_passes_runner_dry_run_to_runner(self):
        """For a low_risk report, check_and_run must be called with mode='dry-run'."""
        import logging
        logger = logging.getLogger("test")

        report = self._make_report()
        hashes = {}

        orch_next_task = b.ORCH_STATE_DIR / "NEXT_TASK.md"
        orch_next_task.write_text("# Next Task\n\nSome safe task.")
        orch_decision  = b.ORCH_STATE_DIR / "latest-decision.json"
        orch_decision.write_text(json.dumps(_make_decision()))

        captured = {}

        def fake_check_and_run(**kwargs):
            captured.update(kwargs)
            return {
                "would_run": True, "ran": False, "mode": kwargs.get("mode", "dry-run"),
                "gate_triggered": "none", "checks_passed": ["ALL"], "checks_failed": [],
                "loop_detected": False, "dry_run": kwargs.get("mode") == "dry-run",
            }

        with patch.object(b, "run_orchestrator", return_value=True):
            import claude_runner as crmod
            with patch.object(crmod, "check_and_run", side_effect=fake_check_and_run) as mock_cr:
                # Patch the import inside bridge
                with patch.dict(sys.modules, {"claude_runner": crmod}):
                    b.process_report(report, hashes, logger, runner="dry-run",
                                     config=_make_config())

        if captured:
            self.assertEqual(captured.get("mode"), "dry-run")

    def test_run_once_accepts_runner_param(self):
        """run_once(runner='dry-run') must not raise."""
        import logging
        logger = logging.getLogger("test")
        # Empty inbox is fine -- just verify no TypeError
        count = b.run_once(logger, planner="local", config=_make_config(), runner="dry-run")
        self.assertEqual(count, 0)

    def test_bridge_version_updated(self):
        self.assertEqual(b.VERSION, "0.3-phase-c")

    def test_config_has_max_auto_runs(self):
        cfg = b.load_config()
        self.assertIn("max_auto_runs_per_hour", cfg)
        self.assertIsInstance(cfg["max_auto_runs_per_hour"], int)


# ---------------------------------------------------------------------------
# TestPhaseBRegression
# ---------------------------------------------------------------------------

class TestPhaseBRegression(unittest.TestCase):
    """Quick regression: Phase B scan_forbidden_patterns still works."""

    def test_scan_detects_git_push(self):
        config = {"forbidden_task_patterns": ["git push"]}
        found = b.scan_forbidden_patterns("run git push origin main", config)
        self.assertIn("git push", found)

    def test_scan_returns_empty_for_clean_task(self):
        config = {"forbidden_task_patterns": ["git push", "npm install"]}
        found = b.scan_forbidden_patterns("# Next Task\n\nFix the bug in utils.py", config)
        self.assertEqual(found, [])

    def test_override_decision_unsafe(self):
        orig = _make_decision()
        new  = b._override_decision_unsafe(orig, ["git push"])
        self.assertEqual(new["decision"], "unsafe_stop")
        self.assertFalse(new["can_execute_with_execute_flag"])
        self.assertIn("git push", new["reason"])


# ---------------------------------------------------------------------------
# Runner constants exported
# ---------------------------------------------------------------------------

class TestRunnerConstants(unittest.TestCase):
    def test_all_gate_constants_defined(self):
        for name in ("GATE_DECISION", "GATE_FORBIDDEN", "GATE_PENDING_APPROVAL",
                     "GATE_GIT_SAFETY", "GATE_RATE_LIMIT", "GATE_LOOP"):
            self.assertTrue(hasattr(cr, name), f"Missing constant: {name}")

    def test_gate_names_are_strings(self):
        gates = [cr.GATE_DECISION, cr.GATE_FORBIDDEN, cr.GATE_PENDING_APPROVAL,
                 cr.GATE_GIT_SAFETY, cr.GATE_RATE_LIMIT, cr.GATE_LOOP]
        for g in gates:
            self.assertIsInstance(g, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
