"""
Phase D tests: D2 — SCOPE_CONSTRAINTS_GATE (Gate 8, execution scope constraints).

Run: python tests/test_bridge_phase_d2.py

All tests are unit/integration tests with mocked subprocesses.
No real Claude invocation.  No real OpenAI calls.
No BRIDGE_EXECUTE_ENABLED set in the real environment.

Test classes:
  TestScopeGateUnit        -- _gate_scope_constraints() function directly
  TestScopeGateIntegration -- Gate 8 wired into check_and_run() after Gate 7
  TestDryRunRegression     -- dry-run mode never evaluates Gate 8
"""

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
# Helpers (mirrored from test_bridge_phase_d for self-contained tests)
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


def _scope_config(**overrides):
    scope = {
        "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
        "allow_root_markdown": True,
        "config_read_only": True,
    }
    scope.update(overrides)
    return scope


def _make_config(execution_scope="default"):
    """Build a runner config.  execution_scope:
    "default" -> standard scope config; None -> key absent; dict -> as given."""
    cfg = {
        "forbidden_task_patterns": ["git push", "git tag"],
        "max_auto_runs_per_hour": 3,
        "claude_timeout_seconds": 10,
    }
    if execution_scope == "default":
        cfg["execution_scope"] = _scope_config()
    elif execution_scope is not None:
        cfg["execution_scope"] = execution_scope
    return cfg


# ---------------------------------------------------------------------------
# TestScopeGateUnit — _gate_scope_constraints() in isolation
# ---------------------------------------------------------------------------

class TestScopeGateUnit(unittest.TestCase):

    def test_scope_gate_constant_defined(self):
        """GATE_SCOPE_CONSTRAINTS must equal the canonical string."""
        self.assertEqual(cr.GATE_SCOPE_CONSTRAINTS, "SCOPE_CONSTRAINTS_GATE")

    # --- Allowlist passes ---

    def test_allowed_docs_path_passes(self):
        ok, msg = cr._gate_scope_constraints(
            "Review the changelog section in docs/CHANGES.md.", _make_config())
        self.assertTrue(ok, msg)

    def test_allowed_tests_path_passes(self):
        ok, msg = cr._gate_scope_constraints(
            "Run tests/test_bridge_phase_d.py and confirm all tests pass.",
            _make_config())
        self.assertTrue(ok, msg)

    def test_allowed_scripts_path_passes(self):
        ok, msg = cr._gate_scope_constraints(
            "Review the output of scripts/show-status.ps1.", _make_config())
        self.assertTrue(ok, msg)

    def test_root_markdown_passes_when_enabled(self):
        ok, msg = cr._gate_scope_constraints(
            "Review README.md and report the section count.", _make_config())
        self.assertTrue(ok, msg)

    def test_no_path_references_passes(self):
        ok, msg = cr._gate_scope_constraints(
            "Run the test suite and report the results.", _make_config())
        self.assertTrue(ok, msg)

    def test_prose_slash_is_not_a_path(self):
        """Words like and/or must not be treated as path references."""
        ok, msg = cr._gate_scope_constraints(
            "Decide whether the tests pass and/or need a rerun.", _make_config())
        self.assertTrue(ok, msg)

    # --- Default deny ---

    def test_missing_execution_scope_default_deny(self):
        ok, msg = cr._gate_scope_constraints(
            "Review docs/CHANGES.md.", _make_config(execution_scope=None))
        self.assertFalse(ok)
        self.assertIn("default deny", msg)

    def test_empty_allowlist_default_deny(self):
        cfg = _make_config(execution_scope=_scope_config(allowed_path_prefixes=[]))
        ok, msg = cr._gate_scope_constraints("Review docs/CHANGES.md.", cfg)
        self.assertFalse(ok)
        self.assertIn("default deny", msg)

    def test_root_markdown_fails_when_disabled(self):
        cfg = _make_config(execution_scope=_scope_config(allow_root_markdown=False))
        ok, msg = cr._gate_scope_constraints(
            "Review README.md and report the section count.", cfg)
        self.assertFalse(ok)
        self.assertIn("Root markdown", msg)

    def test_unlisted_relative_path_blocked(self):
        """Positive allowlist: anything not allowlisted fails."""
        ok, msg = cr._gate_scope_constraints(
            "Review state/bridge-status.json for errors.", _make_config())
        self.assertFalse(ok)
        self.assertIn("allowlist", msg)

    # --- Hard blocklist ---

    def test_git_dir_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            "Inspect .git/config for the remote URL.", _make_config())
        self.assertFalse(ok)

    def test_env_file_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            "Read the .env file for the settings.", _make_config())
        self.assertFalse(ok)
        self.assertIn(".env", msg)

    def test_env_local_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            "Read .env.local for the local overrides.", _make_config())
        self.assertFalse(ok)
        self.assertIn(".env", msg)

    def test_parent_traversal_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            "Review ../other-repo/docs/file.md for context.", _make_config())
        self.assertFalse(ok)

    def test_windows_absolute_path_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            r"Copy C:\Temp\notes.md into the docs folder.", _make_config())
        self.assertFalse(ok)
        self.assertIn("absolute", msg.lower())

    def test_windows_system_folder_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            r"List the files in C:\Windows\System32.", _make_config())
        self.assertFalse(ok)

    def test_posix_absolute_path_blocked(self):
        for text in ("Read /etc/passwd for the entries.",
                     "Review /srv/data/report.md for context."):
            ok, msg = cr._gate_scope_constraints(text, _make_config())
            self.assertFalse(ok, f"should block: {text!r}")

    def test_home_directory_references_blocked(self):
        for text in ("Read ~/notes.md.",
                     "Read $HOME/notes.md.",
                     r"Read %USERPROFILE%\notes.md."):
            ok, msg = cr._gate_scope_constraints(text, _make_config())
            self.assertFalse(ok, f"should block: {text!r}")

    def test_tradingview_light_path_blocked(self):
        for text in (
            r"Open C:\Users\eruwa\OneDrive\Desktop\TradingView Light\chart.txt.",
            "Review TradingView Light/settings.json.",
        ):
            ok, msg = cr._gate_scope_constraints(text, _make_config())
            self.assertFalse(ok, f"should block: {text!r}")

    def test_pinescript_agents_path_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            "Update pinescript-agents/agent.md with the new prompt.", _make_config())
        self.assertFalse(ok)

    def test_blocklist_wins_even_if_prefix_allowlisted(self):
        """Config cannot override the hard blocklist."""
        cfg = _make_config(execution_scope=_scope_config(
            allowed_path_prefixes=["docs/", ".git/"]))
        ok, msg = cr._gate_scope_constraints("Inspect .git/HEAD.", cfg)
        self.assertFalse(ok)

    # --- Path normalization ---

    def test_backslash_path_normalization_allows(self):
        ok, msg = cr._gate_scope_constraints(
            r"Review docs\CHANGES.md for accuracy.", _make_config())
        self.assertTrue(ok, msg)

    def test_backslash_parent_traversal_blocked(self):
        ok, msg = cr._gate_scope_constraints(
            r"Review ..\other\file.md for context.", _make_config())
        self.assertFalse(ok)

    # --- config/ read-only handling ---

    def test_config_read_only_reference_passes(self):
        ok, msg = cr._gate_scope_constraints(
            "Check config/bridge.config.json for the rate limit value.",
            _make_config())
        self.assertTrue(ok, msg)

    def test_config_write_reference_blocked(self):
        for text in (
            "Update config/bridge.config.json with a new key.",
            "Edit config/orchestrator.rules.json to add a pattern.",
        ):
            ok, msg = cr._gate_scope_constraints(text, _make_config())
            self.assertFalse(ok, f"should block: {text!r}")
            self.assertIn("config/", msg)

    def test_config_blocked_when_read_only_disabled(self):
        cfg = _make_config(execution_scope=_scope_config(config_read_only=False))
        ok, msg = cr._gate_scope_constraints(
            "Check config/bridge.config.json for the rate limit value.", cfg)
        self.assertFalse(ok)

    # --- Purity ---

    def test_gate_makes_no_subprocess_calls(self):
        """Gate 8 is a pure function: no subprocess.run under any input."""
        with patch("claude_runner.subprocess.run") as mock_run:
            cr._gate_scope_constraints("Review docs/CHANGES.md.", _make_config())
            cr._gate_scope_constraints("Review ../outside/file.md.", _make_config())
            cr._gate_scope_constraints("Read the .env file.", _make_config())
            cr._gate_scope_constraints("anything", _make_config(execution_scope=None))
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Integration test base
# ---------------------------------------------------------------------------

class _ExecuteTestBase(unittest.TestCase):
    """Temp dir with a task file and approvals/ for check_and_run() tests."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.approval_dir = self.tmp / "approvals"
        self.approval_dir.mkdir()
        self.task_path = self.tmp / "NEXT_TASK.md"
        self.task_path.write_text("# Next Task\n\nRun the test suite.\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, env=None, mode="execute", config=None, **kwargs):
        """Call check_and_run with the git subprocess mocked (clean tree)."""
        if config is None:
            config = _make_config()

        def _fake_subproc(cmd, **kw):
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_fake_subproc):
            return cr.check_and_run(
                decision=_make_decision(),
                task_path=self.task_path,
                config=config,
                mode=mode,
                base_dir=self.tmp,
                approval_dir=self.approval_dir,
                env=env,
                **kwargs,
            )


# ---------------------------------------------------------------------------
# TestScopeGateIntegration — Gate 8 wired into check_and_run() after Gate 7
# ---------------------------------------------------------------------------

class TestScopeGateIntegration(_ExecuteTestBase):

    def test_gate8_passes_and_invokes_with_in_scope_task(self):
        """Both signals + in-scope task: Gates 7 and 8 pass, claude invoked (mocked)."""
        self.task_path.write_text(
            "# Next Task\n\nReview docs/STATUS.md and summarize the findings.\n")
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_EXECUTE_ENABLED, result["checks_passed"])
        self.assertIn(cr.GATE_SCOPE_CONSTRAINTS, result["checks_passed"])

    def test_gate8_runs_after_gate7_and_blocks_out_of_scope_task(self):
        """Gate 7 passes, Gate 8 blocks an out-of-scope task; no invocation."""
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        with patch.object(cr, "_invoke_claude") as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_not_called()
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)
        self.assertIn(cr.GATE_EXECUTE_ENABLED, result["checks_passed"],
                      "Gate 7 must have passed before Gate 8 evaluated")
        failed_gates = [e["gate"] for e in result["checks_failed"]]
        self.assertIn(cr.GATE_SCOPE_CONSTRAINTS, failed_gates)

    def test_gate8_blocks_with_missing_scope_config(self):
        """Execute path with no execution_scope config: default deny at Gate 8."""
        with patch.object(cr, "_invoke_claude") as mock_invoke:
            result = self._run(
                env={"BRIDGE_EXECUTE_ENABLED": "1"},
                config=_make_config(execution_scope=None),
            )
        mock_invoke.assert_not_called()
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)

    def test_gate8_not_evaluated_when_gate7_blocks(self):
        """When Gate 7 blocks (env missing), Gate 8 must never run."""
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        with patch.object(cr, "_gate_scope_constraints") as mock_gate8:
            result = self._run(env={})
        mock_gate8.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        self.assertNotIn(cr.GATE_SCOPE_CONSTRAINTS, result["checks_passed"])
        self.assertNotIn(cr.GATE_SCOPE_CONSTRAINTS,
                         [e["gate"] for e in result["checks_failed"]])

    def test_gate8_block_makes_no_non_git_subprocess_calls(self):
        """A Gate 8 block must not spawn any non-git subprocess."""
        self.task_path.write_text("# Next Task\n\nRead the .env file.\n")
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
                env={"BRIDGE_EXECUTE_ENABLED": "1"},
            )

        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)
        self.assertEqual(non_git_calls, [],
                         f"Non-git subprocess calls found: {non_git_calls}")


# ---------------------------------------------------------------------------
# TestDryRunRegression — dry-run mode must never evaluate Gate 8
# ---------------------------------------------------------------------------

class TestDryRunRegression(_ExecuteTestBase):

    def test_dry_run_never_evaluates_gate8(self):
        """Dry-run returns before Gate 7/8 even with an out-of-scope task."""
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        with patch.object(cr, "_gate_scope_constraints") as mock_gate8:
            result = self._run(env=None, mode="dry-run")
        mock_gate8.assert_not_called()
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")

    def test_dry_run_unaffected_by_missing_scope_config(self):
        """Dry-run behavior is unchanged when execution_scope is absent."""
        result = self._run(env=None, mode="dry-run",
                           config=_make_config(execution_scope=None))
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertNotIn(cr.GATE_SCOPE_CONSTRAINTS, result["checks_passed"])
        self.assertNotIn(cr.GATE_SCOPE_CONSTRAINTS,
                         [e["gate"] for e in result["checks_failed"]])

    def test_dry_run_with_env_var_set_still_dry(self):
        """Even with BRIDGE_EXECUTE_ENABLED=1, dry-run stays dry and skips Gate 8."""
        with patch.object(cr, "_gate_scope_constraints") as mock_gate8:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"}, mode="dry-run")
        mock_gate8.assert_not_called()
        self.assertFalse(result["ran"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")


if __name__ == "__main__":
    print("Phase D tests — D2: SCOPE_CONSTRAINTS_GATE (Gate 8)")
    print("No real Claude invocation.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
