"""
Phase D tests: D4 — POST_RUN_DIFF_GATE (Gate 9, post-run diff review).

Run: python tests/test_bridge_phase_d4.py

All tests are unit/integration tests with mocked subprocesses.
No real Claude invocation.  No real OpenAI calls.
No BRIDGE_EXECUTE_ENABLED set in the real environment.
The fake OPENAI_API_KEY below is not a real credential.

Test classes:
  TestCaptureUnit          -- _capture_post_run_diff() with mocked git
  TestClassifyUnit         -- _classify_post_run_diff() pure classification
  TestGateUnit             -- _gate_post_run_diff() pass/block/disabled
  TestD4Integration        -- Gate 9 wired after _invoke_claude()
  TestD4NotReached         -- dry-run / Gate 7 block / D2 block skip D4
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

# git commands that must never appear in D4 capture.
_FORBIDDEN_GIT_SUBCOMMANDS = (
    "reset", "clean", "checkout", "restore", "add", "commit", "push", "tag",
)


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


def _post_cfg(**overrides):
    cfg = {
        "enabled": True,
        "allowed_path_prefixes": ["docs/", "tests/", "scripts/"],
        "allow_root_markdown": True,
        "block_untracked_files": False,
        "block_deleted_files": True,
        "block_binary_files": True,
    }
    cfg.update(overrides)
    return cfg


def _classify(status_text, diff_text="", **cfg_overrides):
    config = {"post_run_diff": _post_cfg(**cfg_overrides)}
    return cr._classify_post_run_diff(diff_text, status_text, config)


def _fake_git_factory(short_out="", diff_out="", stat_out=""):
    """Mocked subprocess.run: clean pre-run porcelain, configurable D4 output."""
    def _side_effect(cmd, **kwargs):
        cmd_list = list(cmd)
        if cmd_list[:2] == ["git", "status"]:
            if "--porcelain" in cmd_list:      # pre-run Gate 4 -- keep clean
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout=short_out, stderr="")
        if cmd_list[:2] == ["git", "diff"]:
            if "--stat" in cmd_list:
                return MagicMock(returncode=0, stdout=stat_out, stderr="")
            return MagicMock(returncode=0, stdout=diff_out, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")
    return _side_effect


# ---------------------------------------------------------------------------
# TestCaptureUnit — _capture_post_run_diff()
# ---------------------------------------------------------------------------

class TestCaptureUnit(unittest.TestCase):

    def test_capture_uses_read_only_git_commands_only(self):
        """Capture must run only git status/diff -- never mutating commands."""
        seen = []

        def _record(cmd, **kwargs):
            seen.append(list(cmd))
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_record):
            out = cr._capture_post_run_diff(Path("."))
        self.assertTrue(out["ok"])
        self.assertTrue(seen, "no git commands captured")
        for cmd in seen:
            self.assertEqual(cmd[0], "git")
            self.assertIn(cmd[1], ("status", "diff"))
            for forbidden in _FORBIDDEN_GIT_SUBCOMMANDS:
                self.assertNotIn(forbidden, cmd)

    def test_capture_collects_status_and_diff(self):
        side = _fake_git_factory(short_out=" M docs/x.md\n",
                                 diff_out="M\tdocs/x.md\n",
                                 stat_out=" docs/x.md | 2 +-\n")
        with patch("subprocess.run", side_effect=side):
            out = cr._capture_post_run_diff(Path("."))
        self.assertTrue(out["ok"])
        self.assertIn("docs/x.md", out["status_text"])
        self.assertIn("docs/x.md", out["diff_text"])

    def test_capture_failure_returns_not_ok(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            out = cr._capture_post_run_diff(Path("."))
        self.assertFalse(out["ok"])
        self.assertIn("git capture failed", out["error"])

    def test_capture_nonzero_exit_returns_not_ok(self):
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=128, stdout="", stderr="")):
            out = cr._capture_post_run_diff(Path("."))
        self.assertFalse(out["ok"])


# ---------------------------------------------------------------------------
# TestClassifyUnit — _classify_post_run_diff()
# ---------------------------------------------------------------------------

class TestClassifyUnit(unittest.TestCase):

    def test_gate_constant_defined(self):
        self.assertEqual(cr.GATE_POST_RUN_DIFF, "POST_RUN_DIFF_GATE")

    def test_empty_status_is_clean(self):
        r = _classify("")
        self.assertEqual(r["classification"], "clean")
        self.assertTrue(r["safe"])

    def test_allowed_docs_change_passes(self):
        r = _classify(" M docs/CHANGES.md\n")
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_allowed_tests_change_passes(self):
        r = _classify(" M tests/test_bridge_phase_d.py\n")
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_allowed_scripts_change_passes(self):
        r = _classify(" M scripts/show-status.ps1\n")
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_root_markdown_passes_when_enabled(self):
        r = _classify(" M README.md\n")
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_root_markdown_blocked_when_disabled(self):
        r = _classify(" M README.md\n", allow_root_markdown=False)
        self.assertEqual(r["classification"], "unexpected_path")
        self.assertFalse(r["safe"])

    def test_env_file_change_is_secrets_risk(self):
        for line in ("?? .env\n", " M .env.local\n"):
            r = _classify(line)
            self.assertEqual(r["classification"], "secrets_risk", line)
            self.assertFalse(r["safe"])

    def test_secret_file_change_is_secrets_risk(self):
        r = _classify(" M docs/credentials.json\n")
        self.assertEqual(r["classification"], "secrets_risk")
        self.assertFalse(r["safe"])

    def test_git_dir_change_is_git_metadata(self):
        r = _classify(" M .git/config\n")
        self.assertEqual(r["classification"], "git_metadata_change")
        self.assertFalse(r["safe"])

    def test_deleted_file_blocks_when_enabled(self):
        r = _classify(" D docs/old.md\n")
        self.assertEqual(r["classification"], "deleted_file")
        self.assertFalse(r["safe"])

    def test_deleted_file_allowed_when_disabled(self):
        r = _classify(" D docs/old.md\n", block_deleted_files=False)
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_binary_extension_blocks_when_enabled(self):
        r = _classify(" M docs/logo.png\n")
        self.assertEqual(r["classification"], "binary_or_large_change")
        self.assertFalse(r["safe"])

    def test_binary_allowed_when_disabled(self):
        r = _classify(" M docs/logo.png\n", block_binary_files=False)
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_binary_detected_from_stat_marker(self):
        r = _classify(" M docs/asset.blob\n",
                      diff_text=" docs/asset.blob | Bin 0 -> 100 bytes\n")
        self.assertEqual(r["classification"], "binary_or_large_change")
        self.assertFalse(r["safe"])

    def test_unexpected_path_blocks(self):
        r = _classify(" M src/rogue.py\n")
        self.assertEqual(r["classification"], "unexpected_path")
        self.assertFalse(r["safe"])

    def test_tradingview_light_path_blocks(self):
        r = _classify(' M "TradingView Light/chart.txt"\n')
        self.assertFalse(r["safe"])
        self.assertEqual(r["classification"], "unexpected_path")

    def test_pinescript_agents_path_blocks(self):
        r = _classify(" M pinescript-agents/agent.md\n")
        self.assertFalse(r["safe"])
        self.assertEqual(r["classification"], "unexpected_path")

    def test_runtime_untracked_artifacts_are_exempt(self):
        """Untracked files under runtime-exempt dirs never block (Gate 4 parity)."""
        status = ("?? state/auto-exchange-status.json\n"
                  "?? inbox/reports/2026-06-10-report.md\n")
        r = _classify(status)
        self.assertEqual(r["classification"], "clean")
        self.assertTrue(r["safe"])
        self.assertEqual(len(r["runtime_untracked"]), 2)
        self.assertEqual(r["untracked_files"], [])

    def test_new_untracked_outside_runtime_is_classified(self):
        """New untracked files outside runtime dirs are not exempt."""
        r = _classify("?? rogue.txt\n")
        self.assertEqual(r["classification"], "unexpected_path")
        self.assertFalse(r["safe"])
        r = _classify("?? docs/new-page.md\n")
        self.assertEqual(r["classification"], "allowed_changes")
        self.assertTrue(r["safe"])

    def test_block_untracked_files_blocks_even_allowed_dirs(self):
        r = _classify("?? docs/new-page.md\n", block_untracked_files=True)
        self.assertEqual(r["classification"], "unexpected_path")
        self.assertFalse(r["safe"])

    def test_severity_secrets_beats_unexpected(self):
        r = _classify(" M src/rogue.py\n?? .env\n")
        self.assertEqual(r["classification"], "secrets_risk")

    def test_unparseable_line_is_unclear(self):
        r = _classify("@@\n")
        self.assertEqual(r["classification"], "unclear")
        self.assertFalse(r["safe"])

    def test_reason_is_summary_not_diff_body(self):
        r = _classify(" M src/rogue.py\n")
        self.assertLess(len(r["reason"]), 400)


# ---------------------------------------------------------------------------
# TestGateUnit — _gate_post_run_diff()
# ---------------------------------------------------------------------------

class TestGateUnit(unittest.TestCase):

    def test_gate_passes_safe_result(self):
        ok, msg = cr._gate_post_run_diff(
            {"classification": "clean", "safe": True, "reason": "x"},
            {"post_run_diff": _post_cfg()})
        self.assertTrue(ok)

    def test_gate_blocks_unsafe_result(self):
        ok, msg = cr._gate_post_run_diff(
            {"classification": "unexpected_path", "safe": False, "reason": "x"},
            {"post_run_diff": _post_cfg()})
        self.assertFalse(ok)
        self.assertIn("blocked", msg)

    def test_disabled_gate_passes_despite_unsafe(self):
        ok, msg = cr._gate_post_run_diff(
            {"classification": "secrets_risk", "safe": False, "reason": "x"},
            {"post_run_diff": _post_cfg(enabled=False)})
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
            "post_run_diff": _post_cfg(),
        }

    def _run(self, env=None, mode="execute", config=None,
             short_out="", diff_out="", stat_out="", **kwargs):
        if config is None:
            config = self._make_config()
        side = _fake_git_factory(short_out=short_out, diff_out=diff_out,
                                 stat_out=stat_out)
        with patch("subprocess.run", side_effect=side):
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

    def _read_events(self):
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# TestD4Integration — Gate 9 wired after _invoke_claude()
# ---------------------------------------------------------------------------

class TestD4Integration(_ExecuteTestBase):

    def test_clean_post_run_diff_passes(self):
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertIn(cr.GATE_POST_RUN_DIFF, result["checks_passed"])
        self.assertEqual(result["post_run_diff"]["classification"], "clean")
        self.assertTrue(result["post_run_diff"]["safe"])

    def test_allowed_docs_change_passes_integration(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M docs/STATUS.md\n")
        self.assertEqual(result["gate_triggered"], "none")
        self.assertEqual(result["post_run_diff"]["classification"], "allowed_changes")

    def test_d4_blocks_even_when_invoke_succeeds(self):
        """An unexpected diff marks the run blocked despite invocation success."""
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                               short_out=" M src/rogue.py\n")
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"], "invocation did happen and must be reported")
        self.assertEqual(result["gate_triggered"], cr.GATE_POST_RUN_DIFF)
        failed = [e["gate"] for e in result["checks_failed"]]
        self.assertIn(cr.GATE_POST_RUN_DIFF, failed)
        self.assertFalse(result["post_run_diff"]["safe"])

    def test_d4_block_writes_blocked_audit_event(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                      short_out=" M src/rogue.py\n")
        events = self._read_events()
        self.assertEqual(len(events), 3)   # gates_passed, claude_invocation, blocked
        blocked = events[-1]
        self.assertEqual(blocked["event_type"], "post_run_diff_blocked")
        self.assertEqual(blocked["gate"], cr.GATE_POST_RUN_DIFF)
        self.assertEqual(blocked["gate_result"], "blocked")
        self.assertFalse(blocked["generated_command_executed"])
        self.assertFalse(blocked["x6_enabled"])

    def test_clean_run_extends_invocation_event_with_summary(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        events = self._read_events()
        self.assertEqual(len(events), 2)   # D3 semantics preserved
        invocation = events[-1]
        self.assertEqual(invocation["event_type"], "claude_invocation")
        self.assertIn("post_run_diff", invocation)
        self.assertEqual(invocation["post_run_diff"]["classification"], "clean")

    def test_capture_failure_blocks_as_unclear(self):
        def _git_fails_after_invoke(cmd, **kwargs):
            cmd_list = list(cmd)
            if "--porcelain" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd_list[:2] == ["git", "status"] or cmd_list[:2] == ["git", "diff"]:
                return MagicMock(returncode=128, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_git_fails_after_invoke):
            with patch.object(cr, "_invoke_claude", return_value=True):
                result = cr.check_and_run(
                    decision=_make_decision(),
                    task_path=self.task_path,
                    config=self._make_config(),
                    mode="execute",
                    base_dir=self.tmp,
                    approval_dir=self.approval_dir,
                    env={"BRIDGE_EXECUTE_ENABLED": "1"},
                )
        self.assertEqual(result["gate_triggered"], cr.GATE_POST_RUN_DIFF)
        self.assertEqual(result["post_run_diff"]["classification"], "unclear")

    def test_audit_summary_excludes_full_diff_body(self):
        """Stat/diff text content must not be copied into the audit log."""
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                      short_out=" M src/rogue.py\n",
                      diff_out="M\tsrc/rogue.py\n",
                      stat_out=" src/UNIQUE-DIFF-MARKER-99 | 5 +++++\n")
        content = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("UNIQUE-DIFF-MARKER-99", content)

    def test_no_secrets_in_audit_or_result(self):
        env = {"BRIDGE_EXECUTE_ENABLED": "1", "OPENAI_API_KEY": _FAKE_OPENAI_KEY}
        with patch.object(cr, "_invoke_claude", return_value=True):
            result = self._run(env=env, short_out=" M src/rogue.py\n")
        content = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_OPENAI_KEY, content)
        self.assertNotIn("OPENAI_API_KEY", content)
        self.assertNotIn(_FAKE_OPENAI_KEY, json.dumps(result))

    def test_disabled_d4_skips_capture_and_passes(self):
        config = self._make_config()
        config["post_run_diff"]["enabled"] = False
        with patch.object(cr, "_capture_post_run_diff") as mock_capture:
            with patch.object(cr, "_invoke_claude", return_value=True):
                result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"},
                                   config=config)
        mock_capture.assert_not_called()
        self.assertEqual(result["gate_triggered"], "none")


# ---------------------------------------------------------------------------
# TestD4NotReached — dry-run / Gate 7 block / D2 block never reach D4
# ---------------------------------------------------------------------------

class TestD4NotReached(_ExecuteTestBase):

    def test_dry_run_does_not_capture_diff(self):
        with patch.object(cr, "_capture_post_run_diff") as mock_capture:
            result = self._run(env=None, mode="dry-run")
        mock_capture.assert_not_called()
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertNotIn("post_run_diff", result)

    def test_dry_run_regression_result_shape_unchanged(self):
        """Dry-run result has no D4 fields and no audit log side effects."""
        result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"}, mode="dry-run")
        self.assertTrue(result["dry_run"])
        self.assertNotIn("post_run_diff", result)
        self.assertFalse(self.audit_path.exists())

    def test_gate7_block_skips_d4(self):
        with patch.object(cr, "_capture_post_run_diff") as mock_capture:
            result = self._run(env={})
        mock_capture.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        self.assertNotIn("post_run_diff", result)

    def test_d2_block_skips_d4(self):
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        with patch.object(cr, "_capture_post_run_diff") as mock_capture:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_capture.assert_not_called()
        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)
        self.assertNotIn("post_run_diff", result)


if __name__ == "__main__":
    print("Phase D tests — D4: POST_RUN_DIFF_GATE (Gate 9)")
    print("No real Claude invocation.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
