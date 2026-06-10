"""
Phase D tests: D6-A — bridge execute-result plumbing.

Run: python tests/test_bridge_phase_d6a.py

All tests are unit/integration tests with mocked check_and_run / orchestrator.
No real Claude invocation.  No real OpenAI calls.  No tests are ever executed
by the bridge plumbing.  No BRIDGE_EXECUTE_ENABLED set in the real
environment ("execute" appears only as a mocked mode string).
The fake OPENAI_API_KEY below is not a real credential.

Test classes:
  TestLoadDeclaredTests    -- load_declared_tests_run() unit tests
  TestBuildExecuteSummary  -- build_execute_summary() unit tests
  TestBridgePlumbing       -- process_report() passthrough + surfacing
  TestDryRunRegression     -- dry-run bridge behavior unchanged
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

_NULL_LOGGER = logging.getLogger("d6a.null")
_NULL_LOGGER.addHandler(logging.NullHandler())


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


def _execute_pass_result():
    return _fake_result(
        mode="execute", dry_run=False, ran=True,
        post_run_diff={
            "classification": "clean", "safe": True, "reason": "no changes",
            "changed_file_count": 0, "untracked_file_count": 0,
            "runtime_untracked_count": 0, "blocked_paths": [],
        },
        test_requirements={
            "classification": "no_changes", "tests_required": False,
            "determinable": True, "required_test_count": 0,
            "required_tests": [], "declared_tests_run_count": 0,
            "passed": True,
        },
    )


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


# ---------------------------------------------------------------------------
# TestLoadDeclaredTests — load_declared_tests_run()
# ---------------------------------------------------------------------------

class TestLoadDeclaredTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.file = self.tmp / "tests-run.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self):
        return {"test_requirements": {"declared_tests_run_file": str(self.file)}}

    def test_valid_file_returns_list(self):
        self.file.write_text(json.dumps(
            {"tests_run": ["python tests/test_bridge_phase_d.py",
                           "python tests/test_bridge_phase_d2.py"]}),
            encoding="utf-8")
        tests = b.load_declared_tests_run(self._config(), _NULL_LOGGER)
        self.assertEqual(tests, ["python tests/test_bridge_phase_d.py",
                                 "python tests/test_bridge_phase_d2.py"])

    def test_absent_file_returns_none(self):
        self.assertIsNone(b.load_declared_tests_run(self._config(), _NULL_LOGGER))

    def test_missing_config_key_returns_none(self):
        self.assertIsNone(b.load_declared_tests_run({}, _NULL_LOGGER))
        self.assertIsNone(b.load_declared_tests_run(
            {"test_requirements": {}}, _NULL_LOGGER))

    def test_invalid_json_returns_none(self):
        self.file.write_text("not json {{{", encoding="utf-8")
        self.assertIsNone(b.load_declared_tests_run(self._config(), _NULL_LOGGER))

    def test_wrong_shape_returns_none(self):
        for content in ('["just", "a", "list"]',
                        '{"tests_run": "not a list"}',
                        '{"other_key": []}'):
            self.file.write_text(content, encoding="utf-8")
            self.assertIsNone(
                b.load_declared_tests_run(self._config(), _NULL_LOGGER),
                f"should be None for: {content}")

    def test_empty_or_non_string_entries_filtered(self):
        self.file.write_text(json.dumps(
            {"tests_run": ["", "  ", 42, None, "python tests/test_x.py"]}),
            encoding="utf-8")
        tests = b.load_declared_tests_run(self._config(), _NULL_LOGGER)
        self.assertEqual(tests, ["python tests/test_x.py"])

    def test_empty_list_returns_none(self):
        self.file.write_text('{"tests_run": []}', encoding="utf-8")
        self.assertIsNone(b.load_declared_tests_run(self._config(), _NULL_LOGGER))


# ---------------------------------------------------------------------------
# TestBuildExecuteSummary — build_execute_summary()
# ---------------------------------------------------------------------------

class TestBuildExecuteSummary(unittest.TestCase):

    def test_none_for_dry_run_result(self):
        self.assertIsNone(b.build_execute_summary(_fake_result()))

    def test_none_for_gate7_fallback_result(self):
        result = _fake_result(mode="execute", dry_run=False,
                              gate_triggered="EXECUTE_ENABLED_GATE")
        self.assertIsNone(b.build_execute_summary(result))

    def test_summary_fields_for_execute_pass(self):
        summary = b.build_execute_summary(_execute_pass_result())
        self.assertEqual(summary["post_run_diff"]["classification"], "clean")
        self.assertTrue(summary["post_run_diff"]["safe"])
        self.assertEqual(summary["test_requirements"]["classification"],
                         "no_changes")
        self.assertFalse(summary["test_requirements"]["tests_required"])
        self.assertTrue(summary["test_requirements"]["determinable"])
        self.assertTrue(summary["test_requirements"]["passed"])
        self.assertNotIn("audit_log_error", summary)

    def test_audit_error_included_and_truncated(self):
        result = _fake_result(audit_log_error="x" * 1000)
        summary = b.build_execute_summary(result)
        self.assertEqual(len(summary["audit_log_error"]), 300)

    def test_summary_never_includes_bodies(self):
        """Only classification/boolean/count fields survive into the summary."""
        result = _execute_pass_result()
        result["post_run_diff"]["reason"] = "UNIQUE-DIFF-BODY-MARKER"
        summary = b.build_execute_summary(result)
        self.assertNotIn("UNIQUE-DIFF-BODY-MARKER", json.dumps(summary))


# ---------------------------------------------------------------------------
# Bridge integration base (mirrors the Phase C harness)
# ---------------------------------------------------------------------------

class _BridgeTestBase(unittest.TestCase):

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
        for d in (b.INBOX_DIR, b.OUTBOX_DIR, b.APPROVAL_DIR, b.LOGS_DIR,
                  b.STATE_DIR):
            d.mkdir(parents=True, exist_ok=True)

        b.ORCH_STATE_DIR.mkdir(parents=True, exist_ok=True)
        (b.ORCH_STATE_DIR / "NEXT_TASK.md").write_text(
            "# Next Task\n\nSome safe task.\n", encoding="utf-8")
        (b.ORCH_STATE_DIR / "latest-decision.json").write_text(
            json.dumps(_make_decision()), encoding="utf-8")

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger(f"d6a.{self.id()}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self.capture)

        self.declared_file = self.tmp / "tests-run.json"

    def tearDown(self):
        self.logger.removeHandler(self.capture)
        for attr, val in self._orig.items():
            setattr(b, attr, val)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self):
        return {
            "forbidden_task_patterns": ["git push", "git tag"],
            "max_auto_runs_per_hour": 3,
            "test_requirements": {
                "declared_tests_run_file": str(self.declared_file),
            },
        }

    def _process(self, runner="dry-run", fake_result=None, config=None,
                 report_name="report.md"):
        """Run process_report with mocked orchestrator + check_and_run."""
        report = b.INBOX_DIR / report_name
        report.write_text(
            f"Test report content for {report_name} with enough length.",
            encoding="utf-8")
        captured = {}

        def fake_check_and_run(**kwargs):
            captured.update(kwargs)
            if fake_result is not None:
                return dict(fake_result)
            return _fake_result(mode=kwargs.get("mode", "dry-run"),
                                dry_run=kwargs.get("mode") == "dry-run")

        with patch.object(b, "run_orchestrator", return_value=True):
            with patch.object(crmod, "check_and_run",
                              side_effect=fake_check_and_run):
                ok = b.process_report(report, {}, self.logger,
                                      planner="local",
                                      config=config or self._config(),
                                      runner=runner)
        return ok, captured

    def _status(self):
        return json.loads(b.STATUS_FILE.read_text(encoding="utf-8"))

    def _log_text(self):
        return "\n".join(self.capture.records)


# ---------------------------------------------------------------------------
# TestBridgePlumbing — passthrough + surfacing
# ---------------------------------------------------------------------------

class TestBridgePlumbing(_BridgeTestBase):

    def test_execute_passes_declared_tests_through(self):
        self.declared_file.write_text(json.dumps(
            {"tests_run": ["python tests/test_bridge_phase_d.py",
                           "python tests/test_bridge_phase_d2.py"]}),
            encoding="utf-8")
        ok, captured = self._process(runner="execute")
        self.assertTrue(ok)
        self.assertEqual(captured.get("mode"), "execute")
        self.assertEqual(captured.get("tests_run"),
                         ["python tests/test_bridge_phase_d.py",
                          "python tests/test_bridge_phase_d2.py"])

    def test_execute_absent_declared_file_passes_none(self):
        ok, captured = self._process(runner="execute")
        self.assertTrue(ok)
        self.assertIsNone(captured.get("tests_run"))

    def test_execute_invalid_declared_file_passes_none(self):
        self.declared_file.write_text("not json {{{", encoding="utf-8")
        ok, captured = self._process(runner="execute")
        self.assertTrue(ok)
        self.assertIsNone(captured.get("tests_run"))

    def test_execute_pass_surfaces_post_run_diff_summary(self):
        ok, _ = self._process(runner="execute",
                              fake_result=_execute_pass_result())
        self.assertTrue(ok)
        status = self._status()
        self.assertIn("execute_summary", status)
        self.assertEqual(
            status["execute_summary"]["post_run_diff"]["classification"],
            "clean")
        self.assertTrue(status["execute_summary"]["post_run_diff"]["safe"])
        self.assertIn("post_run_diff=clean", self._log_text())

    def test_execute_pass_surfaces_test_requirements_summary(self):
        ok, _ = self._process(runner="execute",
                              fake_result=_execute_pass_result())
        self.assertTrue(ok)
        summary = self._status()["execute_summary"]["test_requirements"]
        self.assertEqual(summary["classification"], "no_changes")
        self.assertFalse(summary["tests_required"])
        self.assertTrue(summary["determinable"])
        self.assertTrue(summary["passed"])
        self.assertIn("test_requirements=no_changes", self._log_text())

    def test_gate7_fallback_unchanged(self):
        """Gate 7 fallback result has no D4/D5 fields -- no summary appears."""
        result = _fake_result(mode="execute", dry_run=False,
                              gate_triggered="EXECUTE_ENABLED_GATE",
                              checks_failed=[{"gate": "EXECUTE_ENABLED_GATE",
                                              "reason": "env not set"}])
        ok, _ = self._process(runner="execute", fake_result=result)
        self.assertTrue(ok)
        self.assertNotIn("execute_summary", self._status())
        self.assertNotIn("Runner execute summary", self._log_text())

    def test_audit_log_error_surfaced(self):
        result = _execute_pass_result()
        result["audit_log_error"] = "audit log write failed: simulated"
        ok, _ = self._process(runner="execute", fake_result=result)
        self.assertTrue(ok)
        self.assertEqual(self._status()["execute_summary"]["audit_log_error"],
                         "audit log write failed: simulated")
        self.assertIn("audit_log_error=audit log write failed: simulated",
                      self._log_text())

    def test_no_secrets_in_logs_or_status(self):
        ok, _ = self._process(runner="execute",
                              fake_result=_execute_pass_result())
        self.assertTrue(ok)
        status_text = b.STATUS_FILE.read_text(encoding="utf-8")
        log_text = self._log_text()
        for haystack in (status_text, log_text):
            self.assertNotIn("OPENAI_API_KEY", haystack)
            self.assertNotIn(_FAKE_OPENAI_KEY, haystack)

    def test_no_real_subprocess_spawned(self):
        """With orchestrator and runner mocked, the bridge spawns nothing."""
        with patch("subprocess.run") as mock_run:
            ok, _ = self._process(runner="execute",
                                  fake_result=_execute_pass_result())
        self.assertTrue(ok)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# TestDryRunRegression — dry-run bridge behavior unchanged
# ---------------------------------------------------------------------------

class TestDryRunRegression(_BridgeTestBase):

    def test_dry_run_passes_tests_run_none(self):
        ok, captured = self._process(runner="dry-run")
        self.assertTrue(ok)
        self.assertEqual(captured.get("mode"), "dry-run")
        self.assertIsNone(captured.get("tests_run"))

    def test_dry_run_status_shape_unchanged(self):
        """Dry-run status payload has exactly the pre-D6 keys."""
        ok, _ = self._process(runner="dry-run")
        self.assertTrue(ok)
        status = self._status()
        self.assertEqual(set(status.keys()),
                         {"status", "detail", "timestamp", "version"})
        self.assertNotIn("execute_summary", status)

    def test_dry_run_does_not_read_declared_tests_file(self):
        self.declared_file.write_text(
            '{"tests_run": ["python tests/test_x.py"]}', encoding="utf-8")
        with patch.object(b, "load_declared_tests_run") as mock_load:
            ok, _ = self._process(runner="dry-run")
        self.assertTrue(ok)
        mock_load.assert_not_called()

    def test_dry_run_no_execute_summary_log_line(self):
        ok, _ = self._process(runner="dry-run")
        self.assertTrue(ok)
        self.assertNotIn("Runner execute summary", self._log_text())

    def test_invalid_declared_file_does_not_affect_dry_run(self):
        self.declared_file.write_text("not json {{{", encoding="utf-8")
        ok, captured = self._process(runner="dry-run")
        self.assertTrue(ok)
        self.assertIsNone(captured.get("tests_run"))


if __name__ == "__main__":
    print("Phase D tests — D6-A: bridge execute-result plumbing")
    print("No real Claude invocation.  No OpenAI calls.  No tests executed by the bridge.")
    print()
    unittest.main(verbosity=2)
