"""
Phase D tests: D3 — execution audit log (append-only JSONL).

Run: python tests/test_bridge_phase_d3.py

All tests are unit/integration tests with mocked subprocesses.
No real Claude invocation.  No real OpenAI calls.
No BRIDGE_EXECUTE_ENABLED set in the real environment.
All BRIDGE_EXECUTE_ENABLED / OPENAI_API_KEY values appear only inside
test-local env dicts; the fake key below is not a real credential.

Test classes:
  TestAuditEventUnit       -- _build_execution_audit_event() directly
  TestAuditAppendUnit      -- _append_execution_audit_log() directly
  TestAuditIntegration     -- audit events written by check_and_run()
  TestAuditFailClosed      -- audit write failure blocks execution
  TestDryRunRegression     -- dry-run never writes audit events
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


# A fake, non-functional key used only to assert it never reaches the log.
_FAKE_OPENAI_KEY = "sk-test-faketestkey1234567890abcdef"

_REQUIRED_EVENT_FIELDS = (
    "timestamp_utc", "event_type", "mode", "runner", "task_id", "decision",
    "gate", "gate_result", "reason", "would_run", "ran", "returncode",
    "scope_gate_enabled", "execute_enabled_env_present",
    "execute_enabled_env_exact", "generated_command_executed",
    "real_claude_execution", "x6_enabled",
)


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_bridge_phase_d2 for self-contained tests)
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


def _build_event(**overrides):
    kwargs = {
        "event_type":  "gate_blocked",
        "mode":        "execute",
        "decision":    _make_decision(),
        "gate":        cr.GATE_EXECUTE_ENABLED,
        "gate_result": "blocked",
        "reason":      "test reason",
        "would_run":   True,
        "ran":         False,
        "env":         {},
    }
    kwargs.update(overrides)
    return cr._build_execution_audit_event(**kwargs)


# ---------------------------------------------------------------------------
# TestAuditEventUnit — _build_execution_audit_event() in isolation
# ---------------------------------------------------------------------------

class TestAuditEventUnit(unittest.TestCase):

    def test_audit_gate_constant_defined(self):
        self.assertEqual(cr.GATE_AUDIT, "EXECUTION_AUDIT_GATE")

    def test_event_contains_all_required_fields(self):
        event = _build_event()
        for field in _REQUIRED_EVENT_FIELDS:
            self.assertIn(field, event, f"missing field: {field}")

    def test_safety_invariants_hardcoded_false(self):
        """generated_command_executed and x6_enabled are always False."""
        for overrides in ({}, {"ran": True, "invoked": True},
                          {"event_type": "claude_invocation"}):
            event = _build_event(**overrides)
            self.assertFalse(event["generated_command_executed"])
            self.assertFalse(event["x6_enabled"])

    def test_real_claude_execution_false_by_default(self):
        event = _build_event()
        self.assertFalse(event["real_claude_execution"])

    def test_real_claude_execution_true_only_when_invoked(self):
        event = _build_event(invoked=True)
        self.assertTrue(event["real_claude_execution"])

    def test_env_flags_are_booleans_not_values(self):
        """Env var presence/exactness are recorded as booleans only."""
        event = _build_event(env={"BRIDGE_EXECUTE_ENABLED": "true"})
        self.assertTrue(event["execute_enabled_env_present"])
        self.assertFalse(event["execute_enabled_env_exact"])

        event = _build_event(env={})
        self.assertFalse(event["execute_enabled_env_present"])
        self.assertFalse(event["execute_enabled_env_exact"])

        event = _build_event(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertTrue(event["execute_enabled_env_present"])
        self.assertTrue(event["execute_enabled_env_exact"])

    def test_event_never_contains_env_values_or_api_key(self):
        """Even with secrets in env, no env value appears in the event."""
        env = {
            "BRIDGE_EXECUTE_ENABLED": "some-env-value-xyz",
            "OPENAI_API_KEY": _FAKE_OPENAI_KEY,
        }
        serialized = json.dumps(_build_event(env=env))
        self.assertNotIn(_FAKE_OPENAI_KEY, serialized)
        self.assertNotIn("some-env-value-xyz", serialized)
        self.assertNotIn("OPENAI_API_KEY", serialized)

    def test_task_id_null_when_unavailable(self):
        event = _build_event(task_id=None)
        self.assertIsNone(event["task_id"])
        event = _build_event(task_id="abc123def456")
        self.assertEqual(event["task_id"], "abc123def456")

    def test_scope_gate_enabled_reflects_config(self):
        event = _build_event(config={"execution_scope": {"allowed_path_prefixes": ["docs/"]}})
        self.assertTrue(event["scope_gate_enabled"])
        event = _build_event(config={})
        self.assertFalse(event["scope_gate_enabled"])


# ---------------------------------------------------------------------------
# TestAuditAppendUnit — _append_execution_audit_log() in isolation
# ---------------------------------------------------------------------------

class TestAuditAppendUnit(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.audit_path = self.tmp / "state" / "execution-audit.log.jsonl"
        self.config = {"execution_audit": {"enabled": True, "path": str(self.audit_path)}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_events(self, path=None):
        path = path or self.audit_path
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]

    def test_append_creates_parent_directory(self):
        """Missing parent dirs are created for the audit log path only."""
        nested = self.tmp / "deep" / "nested" / "audit.jsonl"
        cfg = {"execution_audit": {"enabled": True, "path": str(nested)}}
        ok, msg = cr._append_execution_audit_log(_build_event(), cfg)
        self.assertTrue(ok, msg)
        self.assertTrue(nested.exists())

    def test_append_does_not_overwrite(self):
        """Two appends produce two lines; earlier lines are preserved."""
        ok1, _ = cr._append_execution_audit_log(_build_event(reason="first"), self.config)
        ok2, _ = cr._append_execution_audit_log(_build_event(reason="second"), self.config)
        self.assertTrue(ok1 and ok2)
        events = self._read_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["reason"], "first")
        self.assertEqual(events[1]["reason"], "second")

    def test_append_preserves_preexisting_content(self):
        self.audit_path.parent.mkdir(parents=True)
        self.audit_path.write_text('{"existing": true}\n', encoding="utf-8")
        ok, _ = cr._append_execution_audit_log(_build_event(), self.config)
        self.assertTrue(ok)
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"existing": True})

    def test_disabled_audit_skips_write(self):
        cfg = {"execution_audit": {"enabled": False, "path": str(self.audit_path)}}
        ok, msg = cr._append_execution_audit_log(_build_event(), cfg)
        self.assertTrue(ok)
        self.assertIn("disabled", msg)
        self.assertFalse(self.audit_path.exists())

    def test_missing_config_uses_default_path_and_enabled(self):
        """No execution_audit config: enabled by default at the default path."""
        ok, msg = cr._append_execution_audit_log(_build_event(), {}, base_dir=self.tmp)
        self.assertTrue(ok, msg)
        default_path = self.tmp / "state" / "execution-audit.log.jsonl"
        self.assertTrue(default_path.exists())
        self.assertEqual(len(self._read_events(default_path)), 1)

    def test_relative_path_resolves_against_base_dir(self):
        cfg = {"execution_audit": {"enabled": True, "path": "state/audit.jsonl"}}
        ok, _ = cr._append_execution_audit_log(_build_event(), cfg, base_dir=self.tmp)
        self.assertTrue(ok)
        self.assertTrue((self.tmp / "state" / "audit.jsonl").exists())

    def test_write_failure_returns_false(self):
        """An unwritable audit path returns (False, reason) -- no exception."""
        # A directory at the log path makes open(..., "a") fail.
        self.audit_path.parent.mkdir(parents=True)
        self.audit_path.mkdir()
        ok, msg = cr._append_execution_audit_log(_build_event(), self.config)
        self.assertFalse(ok)
        self.assertIn("audit log write failed", msg)


# ---------------------------------------------------------------------------
# Integration test base
# ---------------------------------------------------------------------------

class _ExecuteTestBase(unittest.TestCase):
    """Temp dir with task file, approvals/, and audit path for check_and_run()."""

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
        }

    def _run(self, env=None, mode="execute", config=None, report_hash="", **kwargs):
        if config is None:
            config = self._make_config()

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
                report_hash=report_hash,
                env=env,
                **kwargs,
            )

    def _read_events(self):
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# TestAuditIntegration — audit events written by check_and_run()
# ---------------------------------------------------------------------------

class TestAuditIntegration(_ExecuteTestBase):

    def test_gate7_block_writes_audit_event(self):
        result = self._run(env={})
        self.assertEqual(result["gate_triggered"], cr.GATE_EXECUTE_ENABLED)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"], "gate_blocked")
        self.assertEqual(ev["gate"], cr.GATE_EXECUTE_ENABLED)
        self.assertEqual(ev["gate_result"], "blocked")
        self.assertFalse(ev["ran"])
        self.assertFalse(ev["real_claude_execution"])
        self.assertFalse(ev["execute_enabled_env_present"])

    def test_d2_block_writes_audit_event(self):
        self.task_path.write_text(
            "# Next Task\n\nReview ../other-repo/file.md for context.\n")
        result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertEqual(result["gate_triggered"], cr.GATE_SCOPE_CONSTRAINTS)
        events = self._read_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_type"], "gate_blocked")
        self.assertEqual(ev["gate"], cr.GATE_SCOPE_CONSTRAINTS)
        self.assertEqual(ev["gate_result"], "blocked")
        self.assertFalse(ev["real_claude_execution"])
        self.assertTrue(ev["execute_enabled_env_exact"])

    def test_gates_passed_and_invocation_success_events(self):
        """Gate-stack pass writes a pre-invocation event, then an outcome event."""
        with patch.object(cr, "_invoke_claude", return_value=True) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_called_once()
        self.assertTrue(result["ran"])
        events = self._read_events()
        self.assertEqual(len(events), 2)

        gates_passed, invocation = events
        self.assertEqual(gates_passed["event_type"], "gates_passed")
        self.assertEqual(gates_passed["gate_result"], "passed")
        self.assertFalse(gates_passed["real_claude_execution"],
                         "pre-invocation event must not claim execution")
        self.assertFalse(gates_passed["ran"])

        self.assertEqual(invocation["event_type"], "claude_invocation")
        self.assertTrue(invocation["ran"])
        self.assertEqual(invocation["returncode"], 0)
        self.assertTrue(invocation["real_claude_execution"])

    def test_invocation_failure_event_has_returncode_and_reason(self):
        with patch.object(cr, "_invoke_claude", return_value=False) as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_called_once()
        self.assertFalse(result["ran"])
        events = self._read_events()
        self.assertEqual(len(events), 2)
        invocation = events[-1]
        self.assertEqual(invocation["event_type"], "claude_invocation")
        self.assertFalse(invocation["ran"])
        self.assertEqual(invocation["returncode"], 1)
        self.assertIn("failed", invocation["reason"])

    def test_audit_log_appends_across_runs(self):
        """Repeated runs accumulate events; the log is never overwritten."""
        self._run(env={})
        self._run(env={})
        self._run(env={})
        events = self._read_events()
        self.assertEqual(len(events), 3)

    def test_all_events_keep_safety_invariants_false(self):
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self._run(env={})
        events = self._read_events()
        self.assertGreaterEqual(len(events), 3)
        for ev in events:
            self.assertFalse(ev["generated_command_executed"])
            self.assertFalse(ev["x6_enabled"])

    def test_audit_log_never_contains_openai_key(self):
        """A fake OPENAI_API_KEY in env must never reach the audit log."""
        env = {"BRIDGE_EXECUTE_ENABLED": "1", "OPENAI_API_KEY": _FAKE_OPENAI_KEY}
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env=env)
        content = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_OPENAI_KEY, content)
        self.assertNotIn("OPENAI_API_KEY", content)

    def test_audit_log_never_contains_task_body(self):
        """The task/command body must not be written to the audit log."""
        self.task_path.write_text(
            "# Next Task\n\nReview docs/STATUS.md UNIQUE-BODY-MARKER-42.\n")
        with patch.object(cr, "_invoke_claude", return_value=True):
            self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        content = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("UNIQUE-BODY-MARKER-42", content)

    def test_task_id_from_report_hash(self):
        self._run(env={}, report_hash="a" * 64)
        events = self._read_events()
        self.assertEqual(events[0]["task_id"], "a" * 16)

    def test_task_id_null_without_report_hash(self):
        self._run(env={}, report_hash="")
        events = self._read_events()
        self.assertIsNone(events[0]["task_id"])


# ---------------------------------------------------------------------------
# TestAuditFailClosed — audit write failure blocks execution
# ---------------------------------------------------------------------------

class TestAuditFailClosed(_ExecuteTestBase):

    def test_audit_failure_blocks_execution(self):
        """If the pre-invocation audit write fails, claude is never invoked."""
        # A directory at the log path makes the append fail.
        self.audit_path.parent.mkdir(parents=True)
        self.audit_path.mkdir()
        with patch.object(cr, "_invoke_claude") as mock_invoke:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        mock_invoke.assert_not_called()
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], cr.GATE_AUDIT)
        failed_gates = [e["gate"] for e in result["checks_failed"]]
        self.assertIn(cr.GATE_AUDIT, failed_gates)

    def test_post_invocation_audit_failure_is_surfaced(self):
        """Audit failure after invocation is reported, never silently ignored."""
        real_append = cr._append_execution_audit_log
        calls = {"n": 0}

        def _fail_second(event, config, base_dir=None):
            calls["n"] += 1
            if calls["n"] >= 2:
                return False, "audit log write failed: simulated"
            return real_append(event, config, base_dir=base_dir)

        with patch.object(cr, "_append_execution_audit_log", side_effect=_fail_second):
            with patch.object(cr, "_invoke_claude", return_value=True):
                result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"})
        self.assertTrue(result["ran"])
        self.assertIn("audit_log_error", result)
        self.assertIn("audit log write failed", result["audit_log_error"])


# ---------------------------------------------------------------------------
# TestDryRunRegression — dry-run never writes audit events
# ---------------------------------------------------------------------------

class TestDryRunRegression(_ExecuteTestBase):

    def test_dry_run_writes_no_audit_log(self):
        result = self._run(env=None, mode="dry-run")
        self.assertTrue(result["would_run"])
        self.assertFalse(result["ran"])
        self.assertEqual(result["gate_triggered"], "none")
        self.assertFalse(self.audit_path.exists(),
                         "dry-run must not create an audit log")

    def test_dry_run_does_not_evaluate_d2_or_audit(self):
        """Dry-run returns before Gate 7/8 and never builds audit events."""
        with patch.object(cr, "_gate_scope_constraints") as mock_gate8, \
             patch.object(cr, "_build_execution_audit_event") as mock_build:
            result = self._run(env={"BRIDGE_EXECUTE_ENABLED": "1"}, mode="dry-run")
        mock_gate8.assert_not_called()
        mock_build.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["gate_triggered"], "none")


if __name__ == "__main__":
    print("Phase D tests — D3: execution audit log (append-only JSONL)")
    print("No real Claude invocation.  No OpenAI calls.")
    print()
    unittest.main(verbosity=2)
