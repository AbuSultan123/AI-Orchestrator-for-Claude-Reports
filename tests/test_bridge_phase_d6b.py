"""
Phase D tests: D6-B — post-run block escalation.

Run: python tests/test_bridge_phase_d6b.py

All tests are unit/integration tests with mocked check_and_run / orchestrator.
No real Claude invocation.  No real OpenAI calls.  "execute" appears only as
a mocked mode string; no BRIDGE_EXECUTE_ENABLED in the real environment.
The fake OPENAI_API_KEY below is not a real credential.

Test classes:
  TestEscalationTrigger    -- which results escalate and which never do
  TestEscalationArtifacts  -- PENDING_APPROVAL.md + execution-report content
  TestNoEscalationPaths    -- dry-run / Gate 7 fallback / clean pass
"""

import json
import logging
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bridge as b
import claude_runner as crmod


_FAKE_OPENAI_KEY = "sk-test-faketestkey1234567890abcdef"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decision():
    return {
        "decision": "low_risk_auto_allowed",
        "risk_level": "low",
        "reason": "test",
        "can_execute_with_execute_flag": True,
        "requires_user_approval": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _fake_result(**overrides):
    r = {
        "would_run": True, "ran": False, "mode": "dry-run",
        "gate_triggered": "none", "checks_passed": [], "checks_failed": [],
        "loop_detected": False, "dry_run": True,
    }
    r.update(overrides)
    return r


def _d4_block_result():
    """D4 blocked after a successful invocation; bodies carry markers that
    must never appear in escalation artifacts."""
    return _fake_result(
        mode="execute", dry_run=False, ran=True,
        gate_triggered="POST_RUN_DIFF_GATE",
        checks_failed=[{
            "gate": "POST_RUN_DIFF_GATE",
            "reason": "post-run diff blocked (unexpected_path): 1 blocked "
                      "change(s), e.g. ['src/rogue.py']",
        }],
        post_run_diff={
            "classification": "unexpected_path", "safe": False,
            "reason": "FULL-DIFF-BODY-MARKER should never be copied",
            "changed_file_count": 1, "untracked_file_count": 0,
            "runtime_untracked_count": 0, "blocked_paths": ["src/rogue.py"],
        },
        raw_command_body="FULL-COMMAND-BODY-MARKER never to be copied",
    )


def _d5_block_result():
    return _fake_result(
        mode="execute", dry_run=False, ran=True,
        gate_triggered="TEST_REQUIREMENT_GATE",
        checks_failed=[{
            "gate": "TEST_REQUIREMENT_GATE",
            "reason": "required tests not declared as run (scripts_change): "
                      "4 missing",
        }],
        post_run_diff={
            "classification": "allowed_changes", "safe": True,
            "reason": "1 change(s), all within allowed paths",
            "changed_file_count": 1, "untracked_file_count": 0,
            "runtime_untracked_count": 0, "blocked_paths": [],
        },
        test_requirements={
            "classification": "scripts_change", "tests_required": True,
            "determinable": True, "required_test_count": 4,
            "required_tests": ["python tests/test_bridge_phase_d.py"],
            "declared_tests_run_count": 0, "passed": False,
            "output": "FULL-TEST-OUTPUT-MARKER never to be copied",
        },
    )


def _audit_block_result():
    """D3 fail-closed: audit write failed before invocation (ran=False)."""
    return _fake_result(
        mode="execute", dry_run=False, ran=False,
        gate_triggered="EXECUTION_AUDIT_GATE",
        checks_failed=[{
            "gate": "EXECUTION_AUDIT_GATE",
            "reason": "audit log write failed: simulated",
        }],
    )


def _gate7_block_result():
    return _fake_result(
        mode="execute", dry_run=False,
        gate_triggered="EXECUTE_ENABLED_GATE",
        checks_failed=[{"gate": "EXECUTE_ENABLED_GATE",
                        "reason": "BRIDGE_EXECUTE_ENABLED is not set."}],
    )


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


# ---------------------------------------------------------------------------
# Bridge integration base (mirrors the D6-A harness + EXEC_REPORTS_DIR)
# ---------------------------------------------------------------------------

class _BridgeTestBase(unittest.TestCase):

    def setUp(self):
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

        b.ORCH_STATE_DIR.mkdir(parents=True, exist_ok=True)
        (b.ORCH_STATE_DIR / "NEXT_TASK.md").write_text(
            "# Next Task\n\nSome safe task.\n", encoding="utf-8")
        (b.ORCH_STATE_DIR / "latest-decision.json").write_text(
            json.dumps(_make_decision()), encoding="utf-8")

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger(f"d6b.{self.id()}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self.capture)

    def tearDown(self):
        self.logger.removeHandler(self.capture)
        for attr, val in self._orig.items():
            setattr(b, attr, val)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self):
        return {
            "forbidden_task_patterns": ["git push", "git tag"],
            "max_auto_runs_per_hour": 3,
        }

    def _process(self, runner="dry-run", fake_result=None,
                 report_name="report.md"):
        report = b.INBOX_DIR / report_name
        report.write_text(
            f"Test report content for {report_name} with enough length.",
            encoding="utf-8")

        def fake_check_and_run(**kwargs):
            if fake_result is not None:
                return dict(fake_result)
            return _fake_result(mode=kwargs.get("mode", "dry-run"),
                                dry_run=kwargs.get("mode") == "dry-run")

        with patch.object(b, "run_orchestrator", return_value=True):
            with patch.object(crmod, "check_and_run",
                              side_effect=fake_check_and_run):
                ok = b.process_report(report, {}, self.logger,
                                      planner="local",
                                      config=self._config(), runner=runner)
        return ok

    @property
    def pending_path(self):
        return b.APPROVAL_DIR / "PENDING_APPROVAL.md"

    def _archives(self):
        if not b.EXEC_REPORTS_DIR.exists():
            return []
        return sorted(b.EXEC_REPORTS_DIR.glob("*-execution-blocked.md"))

    def _status(self):
        return json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))

    def _log_text(self):
        return "\n".join(self.capture.records)


# ---------------------------------------------------------------------------
# TestEscalationTrigger
# ---------------------------------------------------------------------------

class TestEscalationTrigger(_BridgeTestBase):

    def test_post_run_diff_gate_escalates(self):
        ok = self._process(runner="execute", fake_result=_d4_block_result())
        self.assertTrue(ok)
        self.assertTrue(self.pending_path.exists())
        self.assertEqual(len(self._archives()), 1)
        self.assertIn("POST_RUN_BLOCK_ESCALATED: gate=POST_RUN_DIFF_GATE",
                      self._log_text())

    def test_test_requirement_gate_escalates(self):
        ok = self._process(runner="execute", fake_result=_d5_block_result())
        self.assertTrue(ok)
        self.assertTrue(self.pending_path.exists())
        self.assertEqual(len(self._archives()), 1)

    def test_execution_audit_gate_escalates(self):
        ok = self._process(runner="execute", fake_result=_audit_block_result())
        self.assertTrue(ok)
        self.assertTrue(self.pending_path.exists())
        self.assertEqual(len(self._archives()), 1)

    def test_escalation_works_even_when_ran_true(self):
        """A successful invocation followed by a D4 block still escalates,
        and ran stays truthful in the artifacts."""
        self._process(runner="execute", fake_result=_d4_block_result())
        content = self.pending_path.read_text(encoding="utf-8")
        self.assertIn("**ran:** True", content)
        self.assertIn("**Gate triggered:** POST_RUN_DIFF_GATE", content)

    def test_status_file_includes_escalation_summary(self):
        self._process(runner="execute", fake_result=_d4_block_result())
        status = self._status()
        esc = status["execute_summary"]["escalation"]
        self.assertTrue(esc["escalated"])
        self.assertEqual(esc["gate"], "POST_RUN_DIFF_GATE")
        self.assertIn("PENDING_APPROVAL.md", esc["pending_approval"])
        self.assertIn("execution-blocked.md", esc["execution_report"])

    def test_existing_pause_mechanism_reused_no_extra_flags(self):
        """Only PENDING_APPROVAL.md appears in approvals/ -- no new pause flag."""
        self._process(runner="execute", fake_result=_d4_block_result())
        files = [p.name for p in b.APPROVAL_DIR.iterdir()]
        self.assertEqual(files, ["PENDING_APPROVAL.md"])

    def test_no_real_subprocess_spawned(self):
        with patch("subprocess.run") as mock_run:
            self._process(runner="execute", fake_result=_d4_block_result())
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# TestEscalationArtifacts — content of the pending file and archive
# ---------------------------------------------------------------------------

class TestEscalationArtifacts(_BridgeTestBase):

    def test_pending_approval_required_fields(self):
        self._process(runner="execute", fake_result=_d5_block_result())
        content = self.pending_path.read_text(encoding="utf-8")
        for needle in (
            "**Timestamp:**",
            "**Report:**",
            "**Gate triggered:** TEST_REQUIREMENT_GATE",
            "**Reason:** required tests not declared as run",
            "**Runner/mode:** execute",
            "**would_run:** True",
            "**ran:** True",
            "**Returncode (derived):** 0",
            "classification: allowed_changes",
            "classification: scripts_change",
            "tests_required: True",
            "passed: False",
            "Human review is REQUIRED",
            "NOT automatically approved",
        ):
            self.assertIn(needle, content, f"missing: {needle}")

    def test_archive_contains_gate_reason_and_summaries(self):
        self._process(runner="execute", fake_result=_d4_block_result())
        content = self._archives()[0].read_text(encoding="utf-8")
        self.assertIn("**Gate triggered:** POST_RUN_DIFF_GATE", content)
        self.assertIn("post-run diff blocked (unexpected_path)", content)
        self.assertIn("classification: unexpected_path", content)
        self.assertIn("safe: False", content)

    def test_artifacts_exclude_full_diff_body(self):
        self._process(runner="execute", fake_result=_d4_block_result())
        for path in [self.pending_path] + self._archives():
            self.assertNotIn("FULL-DIFF-BODY-MARKER",
                             path.read_text(encoding="utf-8"))

    def test_artifacts_exclude_full_command_body(self):
        self._process(runner="execute", fake_result=_d4_block_result())
        for path in [self.pending_path] + self._archives():
            self.assertNotIn("FULL-COMMAND-BODY-MARKER",
                             path.read_text(encoding="utf-8"))

    def test_artifacts_exclude_test_output(self):
        self._process(runner="execute", fake_result=_d5_block_result())
        for path in [self.pending_path] + self._archives():
            self.assertNotIn("FULL-TEST-OUTPUT-MARKER",
                             path.read_text(encoding="utf-8"))

    def test_artifacts_and_logs_exclude_secrets(self):
        self._process(runner="execute", fake_result=_d4_block_result())
        haystacks = [self.pending_path.read_text(encoding="utf-8"),
                     self._archives()[0].read_text(encoding="utf-8"),
                     b.STATUS_FILE.read_text(encoding="utf-8"),
                     self._log_text()]
        for haystack in haystacks:
            self.assertNotIn("OPENAI_API_KEY", haystack)
            self.assertNotIn(_FAKE_OPENAI_KEY, haystack)

    def test_audit_block_artifacts_show_not_available_summaries(self):
        """EXECUTION_AUDIT_GATE blocks pre-invocation: ran=False, no D4/D5."""
        self._process(runner="execute", fake_result=_audit_block_result())
        content = self.pending_path.read_text(encoding="utf-8")
        self.assertIn("**ran:** False", content)
        self.assertIn("**Returncode (derived):** 1", content)
        self.assertIn("audit log write failed: simulated", content)
        self.assertIn("- not available", content)


# ---------------------------------------------------------------------------
# TestNoEscalationPaths — dry-run / Gate 7 fallback / clean pass
# ---------------------------------------------------------------------------

class TestNoEscalationPaths(_BridgeTestBase):

    def test_dry_run_does_not_escalate(self):
        ok = self._process(runner="dry-run")
        self.assertTrue(ok)
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])
        self.assertNotIn("POST_RUN_BLOCK_ESCALATED", self._log_text())

    def test_gate7_fallback_does_not_escalate(self):
        ok = self._process(runner="execute", fake_result=_gate7_block_result())
        self.assertTrue(ok)
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])
        self.assertNotIn("POST_RUN_BLOCK_ESCALATED", self._log_text())

    def test_clean_execute_pass_does_not_escalate(self):
        result = _fake_result(
            mode="execute", dry_run=False, ran=True,
            post_run_diff={"classification": "clean", "safe": True},
            test_requirements={"classification": "no_changes",
                               "tests_required": False,
                               "determinable": True, "passed": True},
        )
        ok = self._process(runner="execute", fake_result=result)
        self.assertTrue(ok)
        self.assertFalse(self.pending_path.exists())
        self.assertEqual(self._archives(), [])

    def test_escalation_function_not_called_in_dry_run(self):
        with patch.object(b, "escalate_post_run_block") as mock_esc:
            self._process(runner="dry-run")
        mock_esc.assert_not_called()


if __name__ == "__main__":
    print("Phase D tests — D6-B: post-run block escalation")
    print("No real Claude invocation.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
