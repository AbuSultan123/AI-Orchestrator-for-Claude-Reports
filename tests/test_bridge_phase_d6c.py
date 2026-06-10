"""
Phase D tests: D6-C — end-to-end mocked execute smoke tests.

Run: python tests/test_bridge_phase_d6c.py

Unlike the D6-A/D6-B suites (which mock check_and_run itself), these smoke
tests drive bridge.process_report() through the REAL claude_runner gate stack
(Gates 1-10, D3 audit, D6-A plumbing, D6-B escalation), mocking only:
  - _invoke_claude            (never a real Claude invocation)
  - subprocess.run            (never a real git or any other process)
  - run_orchestrator          (no orchestrator subprocess)

Gate 7 note: the all-gates-pass scenarios simulate the Gate 7 pass by
patching claude_runner._gate_execute_enabled -- BRIDGE_EXECUTE_ENABLED is
NEVER set in the environment (asserted in setUp/tearDown).  Gate 7's own
dual-signal logic is exhaustively covered by tests/test_bridge_phase_d.py.

No OpenAI API calls.  No generated command execution.  No push/tag/release.
The fake OPENAI_API_KEY below is not a real credential.

Test classes:
  TestGate7BlockedSmoke    -- execute runner, Gate 7 blocks pre-invocation
  TestFullPassSmoke        -- all gates pass, mocked invocation success
  TestD4BlockSmoke         -- post-run diff block escalates
  TestD5BlockSmoke         -- test-requirement block escalates
  TestDryRunSmoke          -- dry-run regression, end to end
"""

import json
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

import bridge as b
import claude_runner as crmod


_FAKE_OPENAI_KEY = "sk-test-faketestkey1234567890abcdef"

_PHASE_D_SUITE = [
    "python tests/test_bridge_phase_d.py",
    "python tests/test_bridge_phase_d2.py",
    "python tests/test_bridge_phase_d3.py",
    "python tests/test_bridge_phase_d4.py",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision():
    return {
        "decision": "low_risk_auto_allowed",
        "risk_level": "low",
        "reason": "smoke test",
        "can_execute_with_execute_flag": True,
        "requires_user_approval": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _fake_git_factory(short_out="", diff_out="", stat_out=""):
    """Mocked subprocess.run for the real gate stack:
    clean pre-run porcelain (Gate 4), configurable post-run capture (Gate 9)."""
    def _side_effect(cmd, **kwargs):
        cmd_list = list(cmd)
        if cmd_list[:1] != ["git"]:
            raise AssertionError(f"unexpected non-git subprocess: {cmd_list}")
        if cmd_list[1] == "status":
            if "--porcelain" in cmd_list:
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout=short_out, stderr="")
        if cmd_list[1] == "diff":
            if "--stat" in cmd_list:
                return MagicMock(returncode=0, stdout=stat_out, stderr="")
            return MagicMock(returncode=0, stdout=diff_out, stderr="")
        raise AssertionError(f"unexpected git subcommand: {cmd_list}")
    return _side_effect


class _SmokeTestBase(unittest.TestCase):
    """Redirects all bridge dirs into a temp tree; real check_and_run runs."""

    def setUp(self):
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ,
                         "real environment must never enable execution")
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = {}
        for attr in ("INBOX_DIR", "OUTBOX_DIR", "EXEC_REPORTS_DIR",
                     "APPROVAL_DIR", "LOGS_DIR", "STATE_DIR", "HASH_FILE",
                     "STATUS_FILE", "PID_FILE"):
            self._orig[attr] = getattr(b, attr)

        b.INBOX_DIR        = self.tmp / "inbox"
        b.OUTBOX_DIR       = self.tmp / "outbox" / "tasks"
        b.EXEC_REPORTS_DIR = self.tmp / "outbox" / "execution-reports"
        b.APPROVAL_DIR     = self.tmp / "approvals"
        b.LOGS_DIR         = self.tmp / "logs"
        b.STATE_DIR        = self.tmp / "state"
        b.HASH_FILE        = b.STATE_DIR / "processed-hashes.json"
        b.STATUS_FILE      = b.STATE_DIR / "bridge-status.json"
        b.PID_FILE         = b.STATE_DIR / "bridge.pid"
        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR,
                  b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

        # Real orchestrator state dir (runtime artifacts, gitignored).
        b.ORCH_STATE_DIR.mkdir(parents=True, exist_ok=True)
        (b.ORCH_STATE_DIR / "NEXT_TASK.md").write_text(
            "# Next Task\n\nReview docs/STATUS.md and summarize the findings.\n",
            encoding="utf-8")
        (b.ORCH_STATE_DIR / "latest-decision.json").write_text(
            json.dumps(_make_decision()), encoding="utf-8")

        self.audit_path    = self.tmp / "audit" / "execution-audit.log.jsonl"
        self.declared_file = self.tmp / "tests-run.json"

        self._records = []
        capture = self

        class _Handler(logging.Handler):
            def emit(self, record):
                capture._records.append(record.getMessage())

        self._handler = _Handler()
        self.logger = logging.getLogger(f"d6c.{self.id()}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self._handler)

    def tearDown(self):
        self.logger.removeHandler(self._handler)
        for attr, val in self._orig.items():
            setattr(b, attr, val)
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertNotIn("BRIDGE_EXECUTE_ENABLED", os.environ,
                         "tests must not leak BRIDGE_EXECUTE_ENABLED")

    def _config(self):
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
            "test_requirements": {
                "enabled": True,
                "declared_tests_run_file": str(self.declared_file),
                "docs_only_requires_tests": False,
                "scripts_require_tests": True,
                "source_requires_tests": True,
                "config_requires_tests": True,
                "tests_changes_require_self_test": True,
                "required_test_commands": {
                    "scripts":       list(_PHASE_D_SUITE),
                    "claude_runner": list(_PHASE_D_SUITE),
                },
            },
        }

    def _smoke(self, runner="execute", gate7_pass=False, invoke_return=True,
               short_out="", diff_out="", stat_out="",
               report_name="smoke-report.md"):
        """Run process_report through the REAL check_and_run with mocks."""
        report = b.INBOX_DIR / report_name
        report.write_text(
            f"Smoke test report for {report_name} with enough content.",
            encoding="utf-8")

        git_mock = _fake_git_factory(short_out=short_out, diff_out=diff_out,
                                     stat_out=stat_out)
        invoke_mock = MagicMock(return_value=invoke_return)

        patches = [
            patch.object(b, "run_orchestrator", return_value=True),
            patch("subprocess.run", side_effect=git_mock),
            patch.object(crmod, "_invoke_claude", invoke_mock),
        ]
        if gate7_pass:
            # Simulated dual-signal pass; the env var is never actually set.
            patches.append(patch.object(
                crmod, "_gate_execute_enabled",
                return_value=(True, "both signals present (mocked for D6-C smoke)")))

        started = []
        try:
            for p in patches:
                p.start()
                started.append(p)
            ok = b.process_report(report, {}, self.logger, planner="local",
                                  config=self._config(), runner=runner)
        finally:
            for p in reversed(started):
                p.stop()
        return ok, invoke_mock

    # --- inspection helpers ---

    @property
    def pending_path(self):
        return b.APPROVAL_DIR / "PENDING_APPROVAL.md"

    def _archives(self):
        if not b.EXEC_REPORTS_DIR.exists():
            return []
        return sorted(b.EXEC_REPORTS_DIR.glob("*-execution-blocked.md"))

    def _status(self):
        return json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))

    def _audit_events(self):
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]

    def _log_text(self):
        return "\n".join(self._records)

    def _assert_no_secrets_anywhere(self):
        haystacks = [self._log_text(),
                     b.STATUS_FILE.read_text(encoding="utf-8")]
        if self.audit_path.exists():
            haystacks.append(self.audit_path.read_text(encoding="utf-8"))
        if self.pending_path.exists():
            haystacks.append(self.pending_path.read_text(encoding="utf-8"))
        for a in self._archives():
            haystacks.append(a.read_text(encoding="utf-8"))
        for haystack in haystacks:
            self.assertNotIn("OPENAI_API_KEY", haystack)
            self.assertNotIn(_FAKE_OPENAI_KEY, haystack)


# ---------------------------------------------------------------------------
# TestGate7BlockedSmoke — execute runner without execution signals
# ---------------------------------------------------------------------------

class TestGate7BlockedSmoke(_SmokeTestBase):

    def test_gate7_blocks_safely_end_to_end(self):
        ok, invoke_mock = self._smoke(runner="execute", gate7_pass=False)
        self.assertTrue(ok)
        invoke_mock.assert_not_called()
        # No post-run artifacts, no escalation.
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])
        self.assertNotIn("execute_summary", self._status())
        self.assertIn("EXECUTE_ENABLED_GATE", self._log_text())
        # D3 audit recorded the pre-run block (no invocation event).
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "gate_blocked")
        self.assertEqual(events[0]["gate"], "EXECUTE_ENABLED_GATE")
        self.assertFalse(events[0]["real_claude_execution"])
        self._assert_no_secrets_anywhere()


# ---------------------------------------------------------------------------
# TestFullPassSmoke — all gates pass, mocked invocation success
# ---------------------------------------------------------------------------

class TestFullPassSmoke(_SmokeTestBase):

    def test_clean_run_passes_all_gates(self):
        ok, invoke_mock = self._smoke(runner="execute", gate7_pass=True)
        self.assertTrue(ok)
        invoke_mock.assert_called_once()
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])

        status = self._status()
        self.assertIn("execute_summary", status)
        summary = status["execute_summary"]
        self.assertEqual(summary["post_run_diff"]["classification"], "clean")
        self.assertTrue(summary["post_run_diff"]["safe"])
        self.assertEqual(summary["test_requirements"]["classification"],
                         "no_changes")
        self.assertTrue(summary["test_requirements"]["passed"])
        self.assertNotIn("escalation", summary)

        events = self._audit_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "gates_passed")
        self.assertEqual(events[1]["event_type"], "claude_invocation")
        self.assertTrue(events[1]["real_claude_execution"])
        self.assertTrue(events[1]["ran"])
        self.assertIn("post_run_diff", events[1])
        self.assertIn("test_requirements", events[1])
        self._assert_no_secrets_anywhere()

    def test_allowed_scripts_change_with_declared_tests_passes(self):
        """End-to-end D6-A plumbing: declared-tests file satisfies Gate 10."""
        self.declared_file.write_text(
            json.dumps({"tests_run": list(_PHASE_D_SUITE)}), encoding="utf-8")
        ok, invoke_mock = self._smoke(runner="execute", gate7_pass=True,
                                      short_out=" M scripts/tool.ps1\n")
        self.assertTrue(ok)
        invoke_mock.assert_called_once()
        self.assertFalse(self.pending_path.exists())
        summary = self._status()["execute_summary"]
        self.assertEqual(summary["post_run_diff"]["classification"],
                         "allowed_changes")
        self.assertEqual(summary["test_requirements"]["classification"],
                         "scripts_change")
        self.assertTrue(summary["test_requirements"]["passed"])
        self._assert_no_secrets_anywhere()


# ---------------------------------------------------------------------------
# TestD4BlockSmoke — POST_RUN_DIFF_GATE block escalates end to end
# ---------------------------------------------------------------------------

class TestD4BlockSmoke(_SmokeTestBase):

    def _run_d4_block(self):
        return self._smoke(
            runner="execute", gate7_pass=True,
            short_out=" M src/rogue.py\n",
            diff_out="M\tsrc/UNIQUE-RAW-DIFF-MARKER.py\n",
        )

    def test_d4_block_escalates(self):
        ok, invoke_mock = self._run_d4_block()
        self.assertTrue(ok)
        invoke_mock.assert_called_once()
        self.assertTrue(self.pending_path.exists())
        self.assertEqual(len(self._archives()), 1)

        content = self.pending_path.read_text(encoding="utf-8")
        self.assertIn("**Gate triggered:** POST_RUN_DIFF_GATE", content)
        self.assertIn("**ran:** True", content)
        self.assertIn("classification: unexpected_path", content)

        summary = self._status()["execute_summary"]
        self.assertEqual(summary["escalation"]["gate"], "POST_RUN_DIFF_GATE")
        self.assertFalse(summary["post_run_diff"]["safe"])

        events = self._audit_events()
        self.assertEqual(events[-1]["event_type"], "post_run_diff_blocked")

    def test_d4_block_leaks_no_raw_diff(self):
        self._run_d4_block()
        for path in [self.pending_path] + self._archives():
            self.assertNotIn("UNIQUE-RAW-DIFF-MARKER",
                             path.read_text(encoding="utf-8"))
        self.assertNotIn("UNIQUE-RAW-DIFF-MARKER",
                         b.STATUS_FILE.read_text(encoding="utf-8"))
        self._assert_no_secrets_anywhere()


# ---------------------------------------------------------------------------
# TestD5BlockSmoke — TEST_REQUIREMENT_GATE block escalates end to end
# ---------------------------------------------------------------------------

class TestD5BlockSmoke(_SmokeTestBase):

    def test_d5_block_escalates(self):
        """Allowed diff but no declared tests: Gate 10 blocks and escalates."""
        ok, invoke_mock = self._smoke(runner="execute", gate7_pass=True,
                                      short_out=" M scripts/tool.ps1\n")
        self.assertTrue(ok)
        invoke_mock.assert_called_once()
        self.assertTrue(self.pending_path.exists())
        self.assertEqual(len(self._archives()), 1)

        content = self.pending_path.read_text(encoding="utf-8")
        self.assertIn("**Gate triggered:** TEST_REQUIREMENT_GATE", content)
        self.assertIn("**ran:** True", content)
        self.assertIn("classification: scripts_change", content)
        self.assertIn("passed: False", content)

        summary = self._status()["execute_summary"]
        self.assertEqual(summary["escalation"]["gate"],
                         "TEST_REQUIREMENT_GATE")
        self.assertTrue(summary["post_run_diff"]["safe"],
                        "diff itself was allowed; only tests were missing")

        events = self._audit_events()
        self.assertEqual(events[-1]["event_type"], "test_requirement_blocked")

    def test_d5_partial_declared_tests_block(self):
        self.declared_file.write_text(
            json.dumps({"tests_run": _PHASE_D_SUITE[:2]}), encoding="utf-8")
        ok, _ = self._smoke(runner="execute", gate7_pass=True,
                            short_out=" M scripts/tool.ps1\n")
        self.assertTrue(ok)
        self.assertTrue(self.pending_path.exists())
        self.assertIn("TEST_REQUIREMENT_GATE",
                      self._status()["execute_summary"]["escalation"]["gate"])

    def test_d5_block_leaks_no_test_output(self):
        self._smoke(runner="execute", gate7_pass=True,
                    short_out=" M scripts/tool.ps1\n")
        for path in [self.pending_path] + self._archives():
            content = path.read_text(encoding="utf-8")
            # Summary only: gate/classification lines, no captured output.
            self.assertNotIn("Traceback", content)
            self.assertNotIn("stdout", content)
        self._assert_no_secrets_anywhere()


# ---------------------------------------------------------------------------
# TestDryRunSmoke — dry-run regression, end to end
# ---------------------------------------------------------------------------

class TestDryRunSmoke(_SmokeTestBase):

    def test_dry_run_unchanged_end_to_end(self):
        ok, invoke_mock = self._smoke(runner="dry-run", gate7_pass=False)
        self.assertTrue(ok)
        invoke_mock.assert_not_called()
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])
        self.assertFalse(self.audit_path.exists(),
                         "dry-run must not create an audit log")
        status = self._status()
        self.assertEqual(set(status.keys()),
                         {"status", "detail", "timestamp", "version"})
        self.assertNotIn("Runner execute summary", self._log_text())
        self.assertNotIn("POST_RUN_BLOCK_ESCALATED", self._log_text())
        self._assert_no_secrets_anywhere()


if __name__ == "__main__":
    print("Phase D tests — D6-C: end-to-end mocked execute smoke")
    print("Real gate stack; mocked invocation/git only.  No OpenAI calls.")
    print("BRIDGE_EXECUTE_ENABLED is never set in the environment.")
    print()
    unittest.main(verbosity=2)
