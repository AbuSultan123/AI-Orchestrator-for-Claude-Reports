"""
Phase D tests: D0 + D1 — EXECUTE_ENABLED_GATE (Gate 7).

Run: python tests/test_bridge_phase_d.py

All tests are unit/integration tests with mocked subprocesses.
No real Claude invocation.  No real OpenAI calls.
No BRIDGE_EXECUTE_ENABLED set in the real environment.

Test classes:
  TestGate7Unit          -- _gate_execute_enabled() function directly
  TestGate7Integration   -- check_and_run() with Gate 7 wired in
  TestDryRunRegression   -- dry-run mode unaffected by Gate 7
"""

import logging
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import claude_runner as cr


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_bridge_phase_c for self-contained tests)
# ---------------------------------------------------------------------------

def _make_decision(d="low_risk_auto_allowed", can_execute=True):
    return {
        "decision": d,
        "risk_level": "low",
        "reason": "test",
        "can_execute_with_execute_flag": can_execute,
        "requires_user_approval": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _make_config():
    return {
        "forbidden_task_patterns": ["git push", "git tag"],
        "max_auto_runs_per_hour": 3,
        "claude_timeout_seconds": 10,
    }


class _ExecuteTestBase(unittest.TestCase):
    """Sets up a temp dir with a task file and approvals/ for integration tests."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.approval_dir = self.tmp / "approvals"
        self.approval_dir.mkdir()
        self.task_path = self.tmp / "NEXT_TASK.md"
        self.task_path.write_text("# Next Task\n\nRun the test suite.\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, env=None, mode="execute", **kwargs):
        """Call check_and_run in execute mode with git subprocess mocked."""
        def _fake_subproc(cmd, **kw):
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_fake_subproc):
            return cr.check_and_run(
                decision=_make_decision(),
                task_path=self.task_path,
                config=_make_config(),
                mode=mode,
                base_dir=self.tmp,
                approval_dir=self.approval_dir,
                env=env,
                **kwargs,
            )


# ---------------------------------------------------------------------------
# TestGate7Unit — _gate_execute_enabled() in isolation
# ---------------------------------------------------------------------------

class TestGate7Unit(unittest.TestCase):

    def test_execute_gate_constant_defined(self):
        """GATE_EXECUTE_ENABLED must equal the canonical string."""
        self.assertEqual(cr.GATE_EXECUTE_ENABLED, "EXECUTE_ENABLED_GATE")

    def test_execute_gate_passes_with_both_signals(self):
        """Gate passes only when mode=execute AND env var is exactly '1'."""
        ok, msg = cr._gate_execute_enabled("execute", env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertTrue(ok)
        self.assertIn("both signals present", msg)

    def test_execute_gate_blocks_without_env_var(self):
        """Gate blocks when BRIDGE_EXECUTE_ENABLED is not in env at all."""
        ok, msg = cr._gate_execute_enabled("execute", env={})
        self.assertFalse(ok)
        self.assertIn("not set", msg)

    def test_execute_gate_env_var_must_be_exactly_one(self):
        """Every near-miss env value must be blocked — only '1' passes."""
        near_misses = ["0", "true", "yes", " 1 ", "1 ", " 1", "True", "TRUE",
                       "false", "False", "on", "ON", "yes", "YES", "enabled"]
        for val in near_misses:
            ok, msg = cr._gate_execute_enabled("execute", env={"BRIDGE_EXECUTE_ENABLED": val})
            self.assertFalse(
                ok,
                f"BRIDGE_EXECUTE_ENABLED={val!r} should be blocked but was allowed",
            )

    def test_execute_gate_blocks_env_without_execute_mode(self):
        """Gate blocks when env var is set but mode is not 'execute'."""
        ok, msg = cr._gate_execute_enabled("dry-run", env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertFalse(ok)
        self.assertIn("not 'execute'", msg)

    def test_execute_gate_blocks_for_unknown_mode(self):
        """Any mode other than 'execute' is rejected by Gate 7."""
        for mode in ("dryrun", "execute-all", "", "EXECUTE", "Execute"):
            ok, _ = cr._gate_execute_enabled(mode, env={"BRIDGE_EXECUTE_ENABLED": "1"})
            self.assertFalse(ok, f"mode={mode!r} should not pass Gate 7")

    def test_execute_gate_uses_os_environ_when_env_is_none(self):
        """When env=None, Gate 7 reads os.environ (default must block without var)."""
        saved = os.environ.pop("BRIDGE_EXECUTE_ENABLED", None)
        try:
            ok, msg = cr._gate_execute_enabled("execute", env=None)
            self.assertFalse(ok)
        finally:
            if saved is not None:
                os.environ["BRIDGE_EXECUTE_ENABLED"] = saved


# ---------------------------------------------------------------------------
# TestGate7Integration — Gate 7 wired into check_and_run()
# ---------------------------------------------------------------------------

class TestGate7Integration(_ExecuteTestBase):

    def test_execute_gate_fallback_logs_info(self):
        """When Gate 7 blocks, the log record must be at INFO level, not WARNING."""
        test_logger = logging.getLogger("test_phase_d.gate7_info")
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        test_logger.addHandler(handler)
        try:
            def _fake_subproc(cmd, **kw):
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("subprocess.run", side_effect=_fake_subproc):
                result = cr.check_and_run(
                    decision=_make_decision(),
                    task_path=self.task_path,
                    config=_make_config(),
                    mode="execute",
                    base_dir=self.tmp,
                    approval_dir=self.approval_dir,
                    env={},
                    logger=test_logger,
                )
        finally:
            test_logger.removeHandler(handler)

        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        gate7_records = [r for r in records if "EXECUTE_ENABLED_GATE" in r.getMessage()]
        self.assertTrue(gate7_records, "No EXECUTE_ENABLED_GATE log record emitted")
        for rec in gate7_records:
            self.assertLessEqual(
                rec.levelno, logging.INFO,
                f"Gate 7 block logged at {rec.levelname}; expected INFO or lower",
            )

    def test_invoke_not_called_when_env_missing(self):
        """_invoke_claude must not be called when BRIDGE_EXECUTE_ENABLED is absent."""
        with patch.object(cr, "_invoke_claude") as mock_invoke:
            result = self._run(env={})
        mock_invoke.assert_not_called()
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)

    def test_invoke_not_called_when_env_value_invalid(self):
        """_invoke_claude must not be called for any near-miss env value."""
        for val in ("0", "true", "yes", " 1 ", "1 ", " 1"):
            with self.subTest(val=val):
                with patch.object(cr, "_invoke_claude") as mock_invoke:
                    result = self._run(env={"BRIDGE_EXECUTE_ENABLED": val})
                mock_invoke.assert_not_called()
                self.assertFalse(result["ran"])
                self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)

    def test_gate7_evaluated_before_subprocess(self):
        """When Gate 7 blocks, no non-git subprocess.run call may occur."""
        non_git_calls = []

        def _side_effect(cmd, **kwargs):
            if cmd and "git" not in str(cmd[0]).lower():
                non_git_calls.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_side_effect):
            result = cr.check_and_run(
                decision=_make_decision(),
                task_path=self.task_path,
                config=_make_config(),
                mode="execute",
                base_dir=self.tmp,
                approval_dir=self.approval_dir,
                env={},
            )

        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        self.assertEqual(
            non_git_calls, [],
            f"Non-git subprocess calls found: {non_git_calls}",
        )

    def test_gate7_passes_and_invokes_when_both_signals_present(self):
        """With both signals, Gate 7 passes and _invoke_claude is called."""
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_EXECUTE_ENABLED, result["checks_passed"])

    def test_gate7_result_structure_on_block(self):
        """Blocked Gate 7 must set would_run=True, ran=False, gate_triggered correctly."""
        result = self._run(env={})
        self.assertTrue(result["would_run"], "would_run should remain True (task was ready)")
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        failed_gates = [e["gate"] for e in result["checks_failed"]]
        self.assertIn(cr.GATE_EXECUTE_ENABLED, failed_gates)


# ---------------------------------------------------------------------------
# TestDryRunRegression — dry-run mode must be completely unaffected
# ---------------------------------------------------------------------------

class TestDryRunRegression(_ExecuteTestBase):

    def test_dry_run_default_unchanged(self):
        """check_and_run in dry-run mode must behave exactly as before Gate 7."""
        result = self._run(env=None, mode="dry-run")
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertNotIn(cr.GATE_EXECUTE_ENABLED, result["checks_passed"])
        self.assertNotIn(cr.GATE_EXECUTE_ENABLED,
                         [e["gate"] for e in result["checks_failed"]])

    def test_dry_run_with_env_var_set_still_dry(self):
        """Even with BRIDGE_EXECUTE_ENABLED=1, dry-run mode stays dry."""
        result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"}, mode="dry-run")
        self.assertFalse(result["ran"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")


if __name__ == "__main__":
    print("Phase D tests — D0+D1: EXECUTE_ENABLED_GATE")
    print("No real Claude invocation.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
