"""
Phase D tests: D5 — TEST_REQUIREMENT_GATE (Gate 10).

Run: python tests/test_bridge_phase_d5.py

All tests are unit/integration tests with mocked subprocesses.
No real Claude invocation.  No real OpenAI calls.  D5 itself never runs
tests -- declared tests are mocked tests_run values passed into
check_and_run().  No BRIDGE_EXECUTE_ENABLED set in the real environment.
The fake OPENAI_API_KEY below is not a real credential.

Test classes:
  TestClassifyUnit         -- _classify_test_requirements() pure classification
  TestGateUnit             -- _gate_test_requirements() pass/block/disabled
  TestD5Integration        -- Gate 10 wired after Gate 9 in check_and_run()
  TestD5NotReached         -- dry-run / Gate 7 / D2 / D4 blocks skip D5
"""

import json
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


_FAKE_OPENAI_KEY = "sk-test-faketestkey1234567890abcdef"

_PHASE_D_SUITE = [
    "python tests/test_bridge_phase_d.py",
    "python tests/test_bridge_phase_d2.py",
    "python tests/test_bridge_phase_d3.py",
    "python tests/test_bridge_phase_d4.py",
]
_AUTO_EXCHANGE_SUITE = [
    "python tests/test_auto_exchange_x3.py",
    "python tests/test_auto_exchange_x4.py",
    "python tests/test_auto_exchange_x5.py",
    "python tests/test_auto_exchange_command_inbox.py",
]
_RISK_SUITE = ["python tests/test_risk_classifier.py"]


# ---------------------------------------------------------------------------
# Helpers
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


def _req_cfg(**overrides):
    cfg = {
        "enabled": True,
        "docs_only_requires_tests": False,
        "scripts_require_tests": True,
        "source_requires_tests": True,
        "config_requires_tests": True,
        "tests_changes_require_self_test": True,
        "required_test_commands": {
            "scripts":         list(_PHASE_D_SUITE),
            "claude_runner":   list(_PHASE_D_SUITE),
            "auto_exchange":   list(_AUTO_EXCHANGE_SUITE),
            "risk_classifier": list(_RISK_SUITE),
        },
    }
    cfg.update(overrides)
    return cfg


def _classify(paths, **cfg_overrides):
    return cr._classify_test_requirements(
        paths, {"test_requirements": _req_cfg(**cfg_overrides)})


def _gate(req, tests_run=None, **cfg_overrides):
    return cr._gate_test_requirements(
        req, {"test_requirements": _req_cfg(**cfg_overrides)},
        tests_run=tests_run)


def _fake_git_factory(short_out=""):
    """Mocked subprocess.run: clean pre-run porcelain, configurable post-run."""
    def _side_effect(cmd, **kwargs):
        cmd_list = list(cmd)
        if cmd_list[:2] == ["git", "status"]:
            if "--porcelain" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout=short_out, stderr="")
        if cmd_list[:2] == ["git", "diff"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")
    return _side_effect


# ---------------------------------------------------------------------------
# TestClassifyUnit — _classify_test_requirements()
# ---------------------------------------------------------------------------

class TestClassifyUnit(unittest.TestCase):

    def test_gate_constant_defined(self):
        self.assertEqual(cr.GATE_TEST_REQUIREMENT, "TEST_REQUIREMENT_GATE")

    def test_no_changes(self):
        r = _classify([])
        self.assertEqual(r["classification"], "no_changes")
        self.assertFalse(r["tests_required"])

    def test_docs_only_no_tests_required_by_default(self):
        r = _classify(["docs/STATUS.md", "README.md"])
        self.assertEqual(r["classification"], "docs_only")
        self.assertFalse(r["tests_required"])

    def test_docs_only_requires_any_test_when_enabled(self):
        r = _classify(["docs/STATUS.md"], docs_only_requires_tests=True)
        self.assertTrue(r["tests_required"])
        self.assertTrue(r["requires_any_test"])

    def test_claude_runner_change_requires_phase_d_tests(self):
        r = _classify(["claude_runner.py"])
        self.assertEqual(r["classification"], "claude_runner_change")
        self.assertTrue(r["tests_required"])
        self.assertEqual(r["required_tests"], _PHASE_D_SUITE)

    def test_auto_exchange_change_requires_auto_exchange_tests(self):
        r = _classify(["auto_exchange.py"])
        self.assertEqual(r["classification"], "auto_exchange_change")
        self.assertEqual(r["required_tests"], _AUTO_EXCHANGE_SUITE)

    def test_risk_classifier_change_requires_risk_tests(self):
        r = _classify(["risk_classifier.py"])
        self.assertEqual(r["classification"], "risk_classifier_change")
        self.assertEqual(r["required_tests"], _RISK_SUITE)

    def test_scripts_change_requires_tests(self):
        r = _classify(["scripts/show-status.ps1"])
        self.assertEqual(r["classification"], "scripts_change")
        self.assertTrue(r["tests_required"])
        self.assertEqual(r["required_tests"], _PHASE_D_SUITE)

    def test_config_change_requires_tests_with_fallback(self):
        """config has no explicit suite -- falls back to claude_runner suite."""
        r = _classify(["config/bridge.config.json"])
        self.assertEqual(r["classification"], "config_change")
        self.assertTrue(r["tests_required"])
        self.assertEqual(r["required_tests"], _PHASE_D_SUITE)

    def test_tests_only_change_requires_self_test(self):
        r = _classify(["tests/test_bridge_phase_d2.py"])
        self.assertEqual(r["classification"], "tests_only")
        self.assertTrue(r["tests_required"])
        self.assertEqual(r["required_tests"],
                         ["python tests/test_bridge_phase_d2.py"])

    def test_unknown_code_change_is_not_determinable(self):
        r = _classify(["src/rogue.py"])
        self.assertEqual(r["classification"], "unknown_code_change")
        self.assertTrue(r["tests_required"])
        self.assertFalse(r["determinable"])

    def test_mixed_change_combines_required_tests(self):
        r = _classify(["docs/STATUS.md", "claude_runner.py", "auto_exchange.py"])
        self.assertEqual(r["classification"], "mixed_change")
        self.assertTrue(r["tests_required"])
        for cmd in _PHASE_D_SUITE + _AUTO_EXCHANGE_SUITE:
            self.assertIn(cmd, r["required_tests"])

    def test_missing_suite_mapping_is_not_determinable(self):
        r = _classify(["scripts/tool.ps1"],
                      required_test_commands={})
        self.assertTrue(r["tests_required"])
        self.assertFalse(r["determinable"])

    def test_backslash_paths_normalized(self):
        r = _classify(["tests\\test_bridge_phase_d2.py"])
        self.assertEqual(r["classification"], "tests_only")
        self.assertEqual(r["required_tests"],
                         ["python tests/test_bridge_phase_d2.py"])

    def test_extract_changed_paths_from_diff_result(self):
        diff_result = {
            "changed_files":    ["docs/a.md", "scripts\\b.ps1"],
            "untracked_files":  ["docs/new.md"],
            "runtime_untracked": ["state/x.json"],
        }
        paths = cr._extract_changed_paths_from_diff_result(diff_result)
        self.assertEqual(paths, ["docs/a.md", "scripts/b.ps1", "docs/new.md"])

    def test_classify_makes_no_subprocess_calls(self):
        """D5 never executes tests: no subprocess from classify or gate."""
        with patch("claude_runner.subprocess.run") as mock_run:
            r = _classify(["claude_runner.py", "src/rogue.py", "docs/a.md"])
            _gate(r, tests_run=_PHASE_D_SUITE)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# TestGateUnit — _gate_test_requirements()
# ---------------------------------------------------------------------------

class TestGateUnit(unittest.TestCase):

    def test_no_tests_required_passes(self):
        ok, msg = _gate(_classify(["docs/STATUS.md"]))
        self.assertTrue(ok, msg)

    def test_all_required_declared_passes(self):
        ok, msg = _gate(_classify(["claude_runner.py"]),
                        tests_run=list(_PHASE_D_SUITE))
        self.assertTrue(ok, msg)

    def test_missing_required_tests_block(self):
        ok, msg = _gate(_classify(["claude_runner.py"]), tests_run=None)
        self.assertFalse(ok)
        self.assertIn("not declared", msg)

    def test_partial_required_tests_block(self):
        ok, msg = _gate(_classify(["claude_runner.py"]),
                        tests_run=_PHASE_D_SUITE[:2])
        self.assertFalse(ok)
        self.assertIn("missing", msg)

    def test_docs_requires_any_blocks_without_declaration(self):
        req = _classify(["docs/STATUS.md"], docs_only_requires_tests=True)
        ok, msg = _gate(req, tests_run=None, docs_only_requires_tests=True)
        self.assertFalse(ok)

    def test_docs_requires_any_passes_with_any_declared(self):
        req = _classify(["docs/STATUS.md"], docs_only_requires_tests=True)
        ok, msg = _gate(req, tests_run=["python tests/test_bridge_phase_d.py"],
                        docs_only_requires_tests=True)
        self.assertTrue(ok, msg)

    def test_tests_only_self_test_declared_passes(self):
        req = _classify(["tests/test_bridge_phase_d2.py"])
        ok, msg = _gate(req, tests_run=["python tests/test_bridge_phase_d2.py"])
        self.assertTrue(ok, msg)

    def test_tests_only_without_self_test_blocks(self):
        req = _classify(["tests/test_bridge_phase_d2.py"])
        ok, msg = _gate(req, tests_run=["python tests/test_risk_classifier.py"])
        self.assertFalse(ok)

    def test_declared_with_extra_flags_satisfies_by_path(self):
        req = _classify(["tests/test_bridge_phase_d2.py"])
        ok, msg = _gate(req,
                        tests_run=["python tests/test_bridge_phase_d2.py -v"])
        self.assertTrue(ok, msg)

    def test_undeterminable_blocks_even_with_declared_tests(self):
        req = _classify(["src/rogue.py"])
        ok, msg = _gate(req, tests_run=list(_PHASE_D_SUITE))
        self.assertFalse(ok)
        self.assertIn("not determinable", msg)

    def test_disabled_gate_passes_despite_requirements(self):
        req = _classify(["claude_runner.py"])
        ok, msg = _gate(req, tests_run=None, enabled=False)
        self.assertTrue(ok)
        self.assertIn("disabled", msg)


# ---------------------------------------------------------------------------
# Integration test base
# ---------------------------------------------------------------------------

class _ExecuteTestBase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.approval_dir = self.tmp / "approvals"
        self.approval_dir.mkdir()
        self.task_path = self.tmp / "NEXT_TASK.md"
        self.task_path.write_text(
            "# Next Task\n\nReview docs/STATUS.md and summarize the findings.\n")
        self.audit_path = self.tmp / "state" / "execution-audit.log.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_config(self):
        return {
            "forbidden_task_patterns": ["git push", "git tag"],
            "max_auto_runs_per_hour": 3,
            "claude_timeout_seconds": 10,
            "execution_scope": {
                "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
                "allow_root_markdown": True,
                "config_read_only": True,
            },
            "execution_audit": {"enabled": True, "path": str(self.audit_path)},
            "post_run_diff": {
                "enabled": True,
                "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
                "allow_root_markdown": True,
                "block_untracked_files": False,
                "block_deleted_files": True,
                "block_binary_files": True,
            },
            "test_requirements": _req_cfg(),
        }

    def _run(self, env=None, mode="execute", config=None, short_out="",
             tests_run=None, **kwargs):
        if config is None:
            config = self._make_config()
        with patch("subprocess.run", side_effect=_fake_git_factory(short_out)):
            return cr.check_and_run(
                decision=_make_decision(),
                task_path=self.task_path,
                config=config,
                mode=mode,
                base_dir=self.tmp,
                approval_dir=self.approval_dir,
                env=env,
                tests_run=tests_run,
                **kwargs,
            )

    def _read_events(self):
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# TestD5Integration — Gate 10 wired after Gate 9
# ---------------------------------------------------------------------------

class TestD5Integration(_ExecuteTestBase):

    def test_clean_run_passes_d5(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_TEST_REQUIREMENT, result["checks_passed"])
        self.assertEqual(result["test_requirements"]["classification"],
                         "no_changes")

    def test_docs_change_passes_without_tests(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M docs/STATUS.md\n")
        self.assertEqual(result["gate_triggered"], "none")
        self.assertEqual(result["test_requirements"]["classification"],
                         "docs_only")
        self.assertFalse(result["test_requirements"]["tests_required"])

    def test_scripts_change_blocks_without_declared_tests(self):
        """D5 blocks even though invocation succeeded and D4 passed."""
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M scripts/tool.ps1\n")
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"], "invocation happened and must be reported")
        self.assertIn(cr.GATE_POST_RUN_DIFF, result["checks_passed"],
                      "D4 must have passed before D5 evaluated")
        self.assertEqual(result["gate_triggered"], cr.GATE_TEST_REQUIREMENT)
        failed = [e["gate"] for e in result["checks_failed"]]
        self.assertIn(cr.GATE_TEST_REQUIREMENT, failed)
        self.assertFalse(result["test_requirements"]["passed"])

    def test_scripts_change_passes_with_declared_tests(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M scripts/tool.ps1\n",
                               tests_run=list(_PHASE_D_SUITE))
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_TEST_REQUIREMENT, result["checks_passed"])
        self.assertTrue(result["test_requirements"]["passed"])

    def test_partial_declared_tests_block(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M scripts/tool.ps1\n",
                               tests_run=_PHASE_D_SUITE[:2])
        self.assertEqual(result["gate_triggered"], cr.GATE_TEST_REQUIREMENT)

    def test_tests_only_change_with_self_test_passes(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(
                env={"BRIDGE_EXECUTE_ENABLED": "1"},
                short_out=" M tests/test_bridge_phase_d2.py\n",
                tests_run=["python tests/test_bridge_phase_d2.py"])
        self.assertEqual(result["gate_triggered"], "none")

    def test_d5_block_writes_blocked_audit_event(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                      short_out=" M scripts/tool.ps1\n")
        events = self._read_events()
        self.assertEqual(len(events), 3)
        blocked = events[-1]
        self.assertEqual(blocked["event_type"], "test_requirement_blocked")
        self.assertEqual(blocked["gate"], cr.GATE_TEST_REQUIREMENT)
        self.assertEqual(blocked["gate_result"], "blocked")
        self.assertIn("test_requirements", blocked)
        self.assertFalse(blocked["x6_enabled"])
        self.assertFalse(blocked["generated_command_executed"])

    def test_clean_run_extends_invocation_event_with_summary(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                      tests_run=["python tests/test_bridge_phase_d.py"])
        events = self._read_events()
        self.assertEqual(len(events), 2)   # D3 semantics preserved
        invocation = events[-1]
        self.assertIn("test_requirements", invocation)
        self.assertEqual(invocation["test_requirements"]["classification"],
                         "no_changes")
        self.assertEqual(
            invocation["test_requirements"]["declared_tests_run_count"], 1)

    def test_d5_never_executes_tests(self):
        """Only git subprocesses may occur; no pytest/unittest/test commands."""
        seen = []

        def _record(cmd, **kwargs):
            seen.append(list(cmd))
            cmd_list = list(cmd)
            if "--porcelain" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd_list[:2] == ["git", "status"]:
                return MagicMock(returncode=0, stdout=" M scripts/tool.ps1\n",
                                 stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_record):
            with patch.object(cr, "_invoke_claude", return_value=True):
                cr.check_and_run(
                    decision=_make_decision(),
                    task_path=self.task_path,
                    config=self._make_config(),
                    mode="execute",
                    base_dir=self.tmp,
                    approval_dir=self.approval_dir,
                    env={"BRIDGE_EXECUTE_ENABLED": "1"},
                    tests_run=list(_PHASE_D_SUITE),
                )
        for cmd in seen:
            self.assertEqual(cmd[0], "git",
                             f"non-git subprocess spawned: {cmd}")

    def test_audit_excludes_test_output_and_secrets(self):
        env = {"BRIDGE_EXECUTE_ENABLED": "1", "OPENAI_API_KEY": _FAKE_OPENAI_KEY}
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env=env, short_out=" M scripts/tool.ps1\n")
        content = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_OPENAI_KEY, content)
        self.assertNotIn("OPENAI_API_KEY", content)
        self.assertNotIn(_FAKE_OPENAI_KEY, json.dumps(result))
        for event in self._read_events():
            summary = event.get("test_requirements")
            if summary:
                self.assertLessEqual(len(summary.get("required_tests", [])), 6)
                self.assertNotIn("output", summary)


# ---------------------------------------------------------------------------
# TestD5NotReached — dry-run / Gate 7 / D2 / D4 blocks never reach D5
# ---------------------------------------------------------------------------

class TestD5NotReached(_ExecuteTestBase):

    def test_dry_run_does_not_evaluate_d5(self):
        with patch.object(cr, "_classify_test_requirements") as mock_classify:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"}, mode="dry-run")
        mock_classify.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertNotIn("test_requirements", result)

    def test_gate7_block_skips_d5(self):
        with patch.object(cr, "_classify_test_requirements") as mock_classify:
            result = self._run(env={})
        mock_classify.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        self.assertNotIn("test_requirements", result)

    def test_d2_block_skips_d5(self):
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        with patch.object(cr, "_classify_test_requirements") as mock_classify:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_classify.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)

    def test_d4_block_skips_d5(self):
        with patch.object(cr, "_classify_test_requirements") as mock_classify:
            with patch.object(cr, "_invoke_claude", return_value=True):
                result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                                   short_out=" M src/rogue.py\n")
        mock_classify.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_POST_RUN_DIFF)
        self.assertNotIn("test_requirements", result)


if __name__ == "__main__":
    print("Phase D tests — D5: TEST_REQUIREMENT_GATE (Gate 10)")
    print("No real Claude invocation.  No OpenAI calls.  No tests executed by D5.")
    print()
    unittest.main(verbosity=2)
